#include "audio.h"
#include "config.h"
#include "upload.h"
#include <opus.h>

// Opus encoder state
static OpusEncoder* opusEncoder = NULL;
static uint8_t opusBuffer[1024];
static int16_t encodeBuffer[OPUS_FRAME_SIZE];

// Ogg page counter
static uint32_t oggPageCounter = 0;

// Queue for audio chunks
static QueueHandle_t audioQueue = NULL;

// Chunk metadata
typedef struct {
    int16_t* data;
    uint32_t samples;
    bool isEnd;  // true = end of utterance
    char filename[64];
} AudioChunkMsg;

// Global state
volatile bool recording = false;
volatile bool vadMode = true;
uint32_t fileIndex = 0;
uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};

// ── Helper functions ───────────────────────────────────────────────

static float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

// High-pass filter (200Hz cutoff)
static float hpPrevX = 0;
static float hpPrevY = 0;
#define HP_ALPHA 0.924  // exp(-2*pi*200/16000)

static void highPassFilter(int16_t* buffer, int count) {
    for (int i = 0; i < count; i++) {
        float x = (float)buffer[i];
        float y = HP_ALPHA * (hpPrevY + x - hpPrevX);
        hpPrevX = x;
        hpPrevY = y;
        buffer[i] = (int16_t)y;
    }
}

// Write Ogg/Opus headers to file
static void writeOggHeaders(File& file) {
    uint8_t opusHead[19] = {
        'O', 'p', 'u', 's', 'H', 'e', 'a', 'd',
        1, 1, 0, 0,
        (uint8_t)(SAMPLE_RATE & 0xFF),
        (uint8_t)((SAMPLE_RATE >> 8) & 0xFF),
        (uint8_t)((SAMPLE_RATE >> 16) & 0xFF),
        (uint8_t)((SAMPLE_RATE >> 24) & 0xFF),
        0, 0, 0
    };
    
    uint8_t oggS[28] = {
        'O', 'g', 'g', 'S', 0, 0x02,
        0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 0, 0, 0, 0,
        0, 0, 0, 0, 1, 19
    };
    
    uint32_t serial = 12345;
    oggS[10] = serial & 0xFF;
    oggS[11] = (serial >> 8) & 0xFF;
    oggS[12] = (serial >> 16) & 0xFF;
    oggS[13] = (serial >> 24) & 0xFF;
    
    uint32_t crc = 0;
    for (int i = 0; i < 27; i++) crc += oggS[i];
    for (int i = 0; i < 19; i++) crc += opusHead[i];
    oggS[22] = crc & 0xFF;
    oggS[23] = (crc >> 8) & 0xFF;
    oggS[24] = (crc >> 16) & 0xFF;
    oggS[25] = (crc >> 24) & 0xFF;
    
    file.write(oggS, 28);
    file.write(opusHead, 19);
}

// Write Ogg page for Opus frame
static void writeOggPage(File& file, uint8_t* data, uint32_t len) {
    uint8_t oggS[28];
    memset(oggS, 0, 28);
    
    oggS[0] = 'O'; oggS[1] = 'g'; oggS[2] = 'g'; oggS[3] = 'S';
    oggS[4] = 0; oggS[5] = 0x00;
    
    uint32_t serial = 12345;
    oggS[10] = serial & 0xFF;
    oggS[11] = (serial >> 8) & 0xFF;
    oggS[12] = (serial >> 16) & 0xFF;
    oggS[13] = (serial >> 24) & 0xFF;
    
    oggS[14] = oggPageCounter & 0xFF;
    oggS[15] = (oggPageCounter >> 8) & 0xFF;
    oggS[16] = (oggPageCounter >> 16) & 0xFF;
    oggS[17] = (oggPageCounter >> 24) & 0xFF;
    oggPageCounter++;
    
    oggS[26] = 1;
    oggS[27] = (uint8_t)len;
    
    uint32_t crc = 0;
    for (int i = 0; i < 27; i++) crc += oggS[i];
    for (uint32_t i = 0; i < len; i++) crc += data[i];
    oggS[22] = crc & 0xFF;
    oggS[23] = (crc >> 8) & 0xFF;
    oggS[24] = (crc >> 16) & 0xFF;
    oggS[25] = (crc >> 24) & 0xFF;
    
    file.write(oggS, 28);
    file.write(data, len);
}

// ── Public API ─────────────────────────────────────────────────────

void audioInit() {
    audioQueue = xQueueCreate(AUDIO_QUEUE_SIZE, sizeof(AudioChunkMsg));
}

void startRecording(uint32_t durationMs) {
    if (recording) return;
    recordDurationMs = durationMs;
    recording = true;
}

void toggleVAD() {
    vadMode = !vadMode;
    LOG("[VAD] Mode: %s", vadMode ? "VAD (auto)" : "Fixed duration");
}

// ── Audio capture task (always running, never blocks) ──────────────

void audioTask(void *pvParameters) {
    // Allocate buffers
    int16_t* chunkBuffer = (int16_t*)ps_malloc(CHUNK_SAMPLES * 2);
    if (!chunkBuffer) chunkBuffer = (int16_t*)malloc(CHUNK_SAMPLES * 2);
    if (!chunkBuffer) { LOG("[AUDIO] Buffer alloc FAILED"); return; }
    LOG("[AUDIO] Chunk buffer ready (%d bytes, %d sec)", CHUNK_SAMPLES * 2, CHUNK_SAMPLES / SAMPLE_RATE);

    // Init I2S mic
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 480,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0
    };
    i2s_pin_config_t pin_config = {
        .bck_io_num = I2S_PIN_NO_CHANGE,
        .ws_io_num = I2S_MIC_CLK,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = I2S_MIC_DIN
    };
    if (i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL) != ESP_OK) {
        LOG("[I2S] Driver install failed"); return;
    }
    if (i2s_set_pin(I2S_NUM_0, &pin_config) != ESP_OK) {
        LOG("[I2S] Pin config failed"); return;
    }
    LOG("[I2S] PDM Mic ready (CLK=%d, DIN=%d)", I2S_MIC_CLK, I2S_MIC_DIN);

    // Init Opus encoder
    opusEncoder = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_RESTRICTED_LOWDELAY, NULL);
    if (!opusEncoder) { LOG("[AUDIO] Opus encoder creation failed"); return; }
    opus_encoder_ctl(opusEncoder, OPUS_SET_BITRATE(OPUS_BITRATE));
    opus_encoder_ctl(opusEncoder, OPUS_SET_COMPLEXITY(1));
    LOG("[AUDIO] Opus ready (bitrate=%d)", OPUS_BITRATE);

    // VAD state
    bool voiceActive = false;
    uint32_t silenceMs = 0;
    uint32_t captured = 0;
    uint32_t startMs = 0;
    char currentFile[64] = {0};

    // Adaptive threshold
    float bgNoise = 200;
    float bgSamples[VAD_BG_SAMPLES];
    int bgIndex = 0;
    int bgCount = 0;
    float currentThreshold = VAD_THRESHOLD;

    // Analysis buffer
    static int16_t analysisBuffer[VAD_ANALYSIS_MS * SAMPLE_RATE / 1000];
    static int analysisIndex = 0;
    static float smoothedRMS = 0;
    int analysisCapacity = VAD_ANALYSIS_MS * SAMPLE_RATE / 1000;

    while (true) {
        // Always read audio — never block
        int chunkSamples = VAD_CHUNK_MS * SAMPLE_RATE / 1000;
        int16_t readBuffer[480];
        size_t bytesRead = 0;
        i2s_read(I2S_NUM_0, readBuffer, chunkSamples * 2, &bytesRead, pdMS_TO_TICKS(10));
        
        if (bytesRead == 0) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        
        int samplesRead = bytesRead / 2;

        // Accumulate for RMS analysis
        int available = analysisCapacity - analysisIndex;
        int toCopy = (samplesRead < available) ? samplesRead : available;
        memcpy(analysisBuffer + analysisIndex, readBuffer, toCopy * 2);
        analysisIndex += toCopy;

        if (analysisIndex >= analysisCapacity) {
            highPassFilter(analysisBuffer, analysisCapacity);
            smoothedRMS = computeRMS(analysisBuffer, analysisCapacity);
            analysisIndex = 0;

            // Update adaptive threshold when idle
            if (!voiceActive) {
                bgSamples[bgIndex] = smoothedRMS;
                bgIndex = (bgIndex + 1) % VAD_BG_SAMPLES;
                if (bgCount < VAD_BG_SAMPLES) bgCount++;
                float sum = 0;
                for (int i = 0; i < bgCount; i++) sum += bgSamples[i];
                bgNoise = sum / bgCount;
                currentThreshold = max((double)(bgNoise * VAD_BG_ADAPT), (double)VAD_THRESHOLD);

                static uint32_t lastIdleLog = 0;
                uint32_t now = millis();
                if (now - lastIdleLog >= 5000) {
                    LOG("[VAD] Idle: RMS=%.0f, bg=%.0f, thresh=%.0f", smoothedRMS, bgNoise, currentThreshold);
                    lastIdleLog = now;
                }
            }
        }

        if (vadMode) {
            if (smoothedRMS > currentThreshold) {
                if (!voiceActive) {
                    voiceActive = true;
                    silenceMs = 0;
                    captured = 0;
                    startMs = millis();
                    snprintf(currentFile, sizeof(currentFile), "lifelog/rec_%05lu.opus", fileIndex++);
                    LOG("[VAD] Voice started — %s (RMS=%.0f)", currentFile, smoothedRMS);
                }
                silenceMs = 0;

                // Copy chunk to buffer
                if (captured + samplesRead <= CHUNK_SAMPLES) {
                    memcpy(chunkBuffer + captured, readBuffer, bytesRead);
                    captured += samplesRead;
                }

                uint32_t elapsed = millis() - startMs;
                static uint32_t lastLog = 0;
                if (elapsed - lastLog >= 5000) {
                    LOG("[VAD] %d sec, RMS=%.0f (thresh=%.0f bg=%.0f)", elapsed / 1000, smoothedRMS, currentThreshold, bgNoise);
                    lastLog = elapsed;
                }

                // Send to queue when buffer full
                if (captured + samplesRead > CHUNK_SAMPLES) {
                    AudioChunkMsg msg;
                    msg.data = chunkBuffer;
                    msg.samples = captured;
                    msg.isEnd = false;
                    strncpy(msg.filename, currentFile, sizeof(msg.filename));
                    
                    // Allocate new buffer for queue (old one will be used by writer)
                    int16_t* newBuffer = (int16_t*)ps_malloc(CHUNK_SAMPLES * 2);
                    if (!newBuffer) newBuffer = (int16_t*)malloc(CHUNK_SAMPLES * 2);
                    if (newBuffer) {
                        memcpy(newBuffer, chunkBuffer, captured * 2);
                        msg.data = newBuffer;
                        xQueueSend(audioQueue, &msg, pdMS_TO_TICKS(100));
                        captured = 0;
                    }
                }
            } else if (voiceActive) {
                silenceMs += VAD_CHUNK_MS;

                if (captured + samplesRead <= CHUNK_SAMPLES) {
                    memcpy(chunkBuffer + captured, readBuffer, bytesRead);
                    captured += samplesRead;
                }

                if (captured + samplesRead > CHUNK_SAMPLES) {
                    AudioChunkMsg msg;
                    msg.data = chunkBuffer;
                    msg.samples = captured;
                    msg.isEnd = false;
                    strncpy(msg.filename, currentFile, sizeof(msg.filename));
                    
                    int16_t* newBuffer = (int16_t*)ps_malloc(CHUNK_SAMPLES * 2);
                    if (!newBuffer) newBuffer = (int16_t*)malloc(CHUNK_SAMPLES * 2);
                    if (newBuffer) {
                        memcpy(newBuffer, chunkBuffer, captured * 2);
                        msg.data = newBuffer;
                        xQueueSend(audioQueue, &msg, pdMS_TO_TICKS(100));
                        captured = 0;
                    }
                }

                if (silenceMs >= VAD_SILENCE_MS) {
                    voiceActive = false;
                    bgCount = 0;
                    bgIndex = 0;
                    
                    // Send end marker
                    if (captured > 0) {
                        AudioChunkMsg msg;
                        int16_t* newBuffer = (int16_t*)ps_malloc(captured * 2);
                        if (!newBuffer) newBuffer = (int16_t*)malloc(captured * 2);
                        if (newBuffer) {
                            memcpy(newBuffer, chunkBuffer, captured * 2);
                            msg.data = newBuffer;
                            msg.samples = captured;
                            msg.isEnd = true;
                            strncpy(msg.filename, currentFile, sizeof(msg.filename));
                            xQueueSend(audioQueue, &msg, pdMS_TO_TICKS(100));
                            captured = 0;
                        }
                    }
                    
                    LOG("[VAD] Voice ended (%d ms)", millis() - startMs);
                    silenceMs = 0;
                }
            }
        } else {
            // Fixed duration mode
            if (captured == 0 && currentFile[0] == '\0') {
                startMs = millis();
                snprintf(currentFile, sizeof(currentFile), "lifelog/rec_%05lu.opus", fileIndex++);
                LOG("[AUDIO] Recording to %s", currentFile);
            }
            
            if (captured + samplesRead <= CHUNK_SAMPLES) {
                memcpy(chunkBuffer + captured, readBuffer, bytesRead);
                captured += samplesRead;
            }
            
            if (captured + samplesRead > CHUNK_SAMPLES) {
                AudioChunkMsg msg;
                int16_t* newBuffer = (int16_t*)ps_malloc(CHUNK_SAMPLES * 2);
                if (!newBuffer) newBuffer = (int16_t*)malloc(CHUNK_SAMPLES * 2);
                if (newBuffer) {
                    memcpy(newBuffer, chunkBuffer, captured * 2);
                    msg.data = newBuffer;
                    msg.samples = captured;
                    msg.isEnd = false;
                    strncpy(msg.filename, currentFile, sizeof(msg.filename));
                    xQueueSend(audioQueue, &msg, pdMS_TO_TICKS(100));
                    captured = 0;
                }
            }
            
            uint32_t elapsed = millis() - startMs;
            if (elapsed >= recordDurationMs) {
                if (captured > 0) {
                    AudioChunkMsg msg;
                    int16_t* newBuffer = (int16_t*)ps_malloc(captured * 2);
                    if (!newBuffer) newBuffer = (int16_t*)malloc(captured * 2);
                    if (newBuffer) {
                        memcpy(newBuffer, chunkBuffer, captured * 2);
                        msg.data = newBuffer;
                        msg.samples = captured;
                        msg.isEnd = true;
                        strncpy(msg.filename, currentFile, sizeof(msg.filename));
                        xQueueSend(audioQueue, &msg, pdMS_TO_TICKS(100));
                        captured = 0;
                    }
                }
                currentFile[0] = '\0';
                recording = false;
            }
        }
    }
}

// ── Writer task (handles SD writes and uploads) ────────────────────

void writerTask(void *pvParameters) {
    File activeFile;
    uint32_t totalEncoded = 0;
    char currentFilename[64] = {0};
    
    // Wait for SD to be ready
    delay(1000);
    
    while (true) {
        AudioChunkMsg msg;
        if (xQueueReceive(audioQueue, &msg, portMAX_DELAY)) {
            // Open new file if needed
            if (currentFilename[0] == '\0' || strcmp(currentFilename, msg.filename) != 0) {
                if (activeFile) {
                    // Close previous file
                    activeFile.close();
                    LOG("[WRITER] Closed %s (%d bytes)", currentFilename, totalEncoded);
                    
                    // Upload and delete
                    if (WiFi.status() == WL_CONNECTED && totalEncoded > 0) {
                        uploadFile(currentFilename);
                        SD.remove(currentFilename);
                        LOG("[WRITER] Uploaded %s", currentFilename);
                    }
                    totalEncoded = 0;
                }
                
                // Open new file
                strncpy(currentFilename, msg.filename, sizeof(currentFilename));
                if (SD.cardType() == CARD_NONE) {
                    LOG("[WRITER] SD card not available");
                    free(msg.data);
                    continue;
                }
                activeFile = SD.open(currentFilename, FILE_WRITE);
                if (activeFile) {
                    oggPageCounter = 0;
                    writeOggHeaders(activeFile);
                    LOG("[WRITER] Opened %s", currentFilename);
                } else {
                    LOG("[WRITER] Failed to open %s", currentFilename);
                    currentFilename[0] = '\0';
                }
            }
            
            // Write audio data
            if (activeFile && msg.samples > 0) {
                // Encode with Opus
                uint32_t pcmIndex = 0;
                while (pcmIndex < msg.samples) {
                    int samplesAvailable = msg.samples - pcmIndex;
                    int samplesToEncode = (samplesAvailable < OPUS_FRAME_SIZE) ? samplesAvailable : OPUS_FRAME_SIZE;
                    
                    memcpy(encodeBuffer, msg.data + pcmIndex, samplesToEncode * 2);
                    if (samplesToEncode < OPUS_FRAME_SIZE) {
                        memset(encodeBuffer + samplesToEncode, 0, (OPUS_FRAME_SIZE - samplesToEncode) * 2);
                    }
                    
                    int bytesEncoded = opus_encode(opusEncoder, encodeBuffer, OPUS_FRAME_SIZE,
                                                   opusBuffer, sizeof(opusBuffer));
                    
                    if (bytesEncoded > 0) {
                        writeOggPage(activeFile, opusBuffer, bytesEncoded);
                        totalEncoded += bytesEncoded;
                    }
                    pcmIndex += samplesToEncode;
                }
                activeFile.flush();
            }
            
            // End of utterance
            if (msg.isEnd) {
                if (activeFile) {
                    activeFile.close();
                    LOG("[WRITER] Closed %s (%d bytes)", currentFilename, totalEncoded);
                    
                    if (WiFi.status() == WL_CONNECTED && totalEncoded > 0) {
                        uploadFile(currentFilename);
                        SD.remove(currentFilename);
                        LOG("[WRITER] Uploaded %s", currentFilename);
                    }
                    totalEncoded = 0;
                    currentFilename[0] = '\0';
                }
            }
            
            // Free the buffer
            free(msg.data);
        }
    }
}
