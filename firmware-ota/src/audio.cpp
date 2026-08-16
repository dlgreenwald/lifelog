#include "audio.h"
#include "config.h"
#include "upload.h"
#include <opus.h>
#include <oggz.h>

// Opus encoder state
static OpusEncoder* opusEncoder = NULL;

// Oggz state
static OGGZ *oggz = NULL;
static long oggzSerialno = -1;
static long oggzPacketno = 0;
static int64_t oggzGranulePos = 0;

// Global state
volatile bool recording = false;
volatile bool vadMode = true;
uint32_t fileIndex = 0;
uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};

// Queue settings
#define AUDIO_QUEUE_SIZE  10
#define CHUNK_SAMPLES   (SAMPLE_RATE * 5)

// ── Helper functions ───────────────────────────────────────────────

static float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

// High-pass filter (50Hz cutoff)
static float hpPrevX = 0;
static float hpPrevY = 0;
#define HP_ALPHA 0.9806

static void highPassFilter(int16_t* buffer, int count) {
    for (int i = 0; i < count; i++) {
        float x = (float)buffer[i];
        float y = HP_ALPHA * (hpPrevY + x - hpPrevX);
        hpPrevX = x;
        hpPrevY = y;
        buffer[i] = (int16_t)y;
    }
}

// Audio format: define AUDIO_FORMAT_WAV for WAV, default is Opus
// #define AUDIO_FORMAT_WAV

// High-pass filter: define ENABLE_HPF to enable (disabled by default)
// #define ENABLE_HPF

// Digital gain to boost PDM mic signal (disabled for now)
#define MIC_GAIN 1  // 1x gain (no boost)

static void applyGain(int16_t* buffer, int count) {
    for (int i = 0; i < count; i++) {
        int32_t sample = (int32_t)buffer[i] * MIC_GAIN;
        if (sample > 32767) sample = 32767;
        if (sample < -32768) sample = -32768;
        buffer[i] = (int16_t)sample;
    }
}

// ── WAV header writing (minimal, tested implementation) ─────────────

static void writeWavHeader(File& file, uint32_t dataSize) {
    // Build header in a buffer first, then write atomically
    uint8_t header[44];
    
    // RIFF header
    header[0] = 'R'; header[1] = 'I'; header[2] = 'F'; header[3] = 'F';
    uint32_t fileSize = 36 + dataSize;
    memcpy(header + 4, &fileSize, 4);
    header[8] = 'W'; header[9] = 'A'; header[10] = 'V'; header[11] = 'E';
    
    // fmt subchunk
    header[12] = 'f'; header[13] = 'm'; header[14] = 't'; header[15] = ' ';
    uint32_t fmtSize = 16;
    memcpy(header + 16, &fmtSize, 4);
    uint16_t audioFormat = 1;  // PCM
    memcpy(header + 20, &audioFormat, 2);
    uint16_t numChannels = 1;
    memcpy(header + 22, &numChannels, 2);
    uint32_t sampleRate = SAMPLE_RATE;
    memcpy(header + 24, &sampleRate, 4);
    uint32_t byteRate = SAMPLE_RATE * 2;
    memcpy(header + 28, &byteRate, 4);
    uint16_t blockAlign = 2;
    memcpy(header + 32, &blockAlign, 2);
    uint16_t bitsPerSample = 16;
    memcpy(header + 34, &bitsPerSample, 2);
    
    // data subchunk
    header[36] = 'd'; header[37] = 'a'; header[38] = 't'; header[39] = 'a';
    memcpy(header + 40, &dataSize, 4);
    
    file.write(header, 44);
}

static void updateWavHeader(File& file, uint32_t dataSize) {
    uint32_t fileSize = 36 + dataSize;
    file.seek(4);
    file.write((uint8_t*)&fileSize, 4);
    file.seek(40);
    file.write((uint8_t*)&dataSize, 4);
}

// ── Ogg/Opus writing using codec-ogg library ───────────────────────

static void writeOpusHeaders(OGGZ *oggz, long serialno) {
    // OpusHead identification header
    uint8_t opusHead[19];
    memset(opusHead, 0, sizeof(opusHead));
    memcpy(opusHead, "OpusHead", 8);
    opusHead[8] = 1;    // Version
    opusHead[9] = 1;    // Channel count (mono)
    opusHead[10] = 0;   // Pre-skip low byte (3840 = 0x0F00)
    opusHead[11] = 15;  // Pre-skip high byte (0x0F = 15)
    // Sample rate (little endian)
    opusHead[12] = SAMPLE_RATE & 0xFF;
    opusHead[13] = (SAMPLE_RATE >> 8) & 0xFF;
    opusHead[14] = (SAMPLE_RATE >> 16) & 0xFF;
    opusHead[15] = (SAMPLE_RATE >> 24) & 0xFF;
    opusHead[16] = 0;   // Output gain
    opusHead[17] = 0;   // Output gain
    opusHead[18] = 0;   // Channel mapping family
    
    ogg_packet opHead;
    memset(&opHead, 0, sizeof(opHead));
    opHead.packet = opusHead;
    opHead.bytes = sizeof(opusHead);
    opHead.b_o_s = 1;
    opHead.e_o_s = 0;
    opHead.granulepos = 0;
    opHead.packetno = oggzPacketno++;
    
    oggz_write_feed(oggz, &opHead, serialno, OGGZ_FLUSH_BEFORE, NULL);
    
    // OpusTags comment header
    char vendor[] = "LifeLog";
    uint8_t opusTags[8 + 4 + 7 + 4];  // Magic + vendor len + vendor + comment count
    memcpy(opusTags, "OpusTags", 8);
    // Vendor string length (little endian)
    opusTags[8] = 7;
    opusTags[9] = 0;
    opusTags[10] = 0;
    opusTags[11] = 0;
    memcpy(opusTags + 12, vendor, 7);
    // User comment list length (0 comments)
    opusTags[19] = 0;
    opusTags[20] = 0;
    opusTags[21] = 0;
    opusTags[22] = 0;
    
    ogg_packet opTags;
    memset(&opTags, 0, sizeof(opTags));
    opTags.packet = opusTags;
    opTags.bytes = sizeof(opusTags);
    opTags.b_o_s = 0;
    opTags.e_o_s = 0;
    opTags.granulepos = 0;
    opTags.packetno = oggzPacketno++;
    
    oggz_write_feed(oggz, &opTags, serialno, OGGZ_FLUSH_BEFORE, NULL);
}

static void writeOpusFrame(OGGZ *oggz, long serialno, uint8_t* data, int len, int samples) {
    ogg_packet op;
    memset(&op, 0, sizeof(op));
    op.packet = data;
    op.bytes = len;
    op.b_o_s = 0;
    op.e_o_s = 0;
    // Granule position must be in 48kHz units (our audio is 16kHz, so multiply by 3)
    oggzGranulePos += samples * 3;
    op.granulepos = oggzGranulePos;
    op.packetno = oggzPacketno++;
    
    oggz_write_feed(oggz, &op, serialno, 0, NULL);
}

static void flushOggz(OGGZ *oggz) {
    unsigned char buf[4096];
    long n;
    while ((n = oggz_write(oggz, sizeof(buf))) > 0) {
        // In a real implementation, write buf to file
    }
}

// ── Public API ─────────────────────────────────────────────────────

// Queue for audio chunks
static QueueHandle_t audioQueue = NULL;

typedef struct {
    int16_t* data;
    uint32_t samples;
    bool isEnd;
    char filename[64];
} AudioChunkMsg;

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

// ── Audio capture task ─────────────────────────────────────────────

void audioTask(void *pvParameters) {
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
    #ifndef AUDIO_FORMAT_WAV
    opusEncoder = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_RESTRICTED_LOWDELAY, NULL);
    if (!opusEncoder) { LOG("[AUDIO] Opus encoder creation failed"); return; }
    opus_encoder_ctl(opusEncoder, OPUS_SET_BITRATE(OPUS_BITRATE));
    opus_encoder_ctl(opusEncoder, OPUS_SET_COMPLEXITY(1));
    LOG("[AUDIO] Opus ready (bitrate=%d)", OPUS_BITRATE);
    #else
    LOG("[AUDIO] WAV mode (no Opus)");
    #endif

    // VAD state
    bool voiceActive = false;
    uint32_t silenceMs = 0;
    uint32_t captured = 0;
    uint32_t startMs = 0;
    char currentFile[64] = {0};

    // Adaptive threshold
    float bgNoise = 200;
    float bgSamples[50];
    int bgIndex = 0;
    int bgCount = 0;
    float currentThreshold = 20;

    // Analysis buffer
    static int16_t analysisBuffer[3200];  // 200ms
    static int analysisIndex = 0;
    static float smoothedRMS = 0;

    while (true) {
        // Always read audio
        int chunkSamples = 480;  // 30ms
        int16_t readBuffer[480];
        size_t bytesRead = 0;
        i2s_read(I2S_NUM_0, readBuffer, chunkSamples * 2, &bytesRead, pdMS_TO_TICKS(10));
        
        if (bytesRead == 0) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }
        
        int samplesRead = bytesRead / 2;

        // Apply digital gain to boost PDM mic signal
        applyGain(readBuffer, samplesRead);

        // RMS analysis
        int available = 3200 - analysisIndex;
        int toCopy = (samplesRead < available) ? samplesRead : available;
        memcpy(analysisBuffer + analysisIndex, readBuffer, toCopy * 2);
        analysisIndex += toCopy;

        if (analysisIndex >= 3200) {
            #ifdef ENABLE_HPF
            highPassFilter(analysisBuffer, 3200);
            #endif
            smoothedRMS = computeRMS(analysisBuffer, 3200);
            analysisIndex = 0;

            if (!voiceActive) {
                bgSamples[bgIndex] = smoothedRMS;
                bgIndex = (bgIndex + 1) % 50;
                if (bgCount < 50) bgCount++;
                float sum = 0;
                for (int i = 0; i < bgCount; i++) sum += bgSamples[i];
                bgNoise = sum / bgCount;
                currentThreshold = max((double)(bgNoise * 1.5), (double)20);

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
                    #ifdef AUDIO_FORMAT_WAV
                    snprintf(currentFile, sizeof(currentFile), "/lifelog/rec_%05lu.wav", fileIndex++);
                    #else
                    snprintf(currentFile, sizeof(currentFile), "/lifelog/rec_%05lu.opus", fileIndex++);
                    #endif
                    LOG("[VAD] Voice started — %s (RMS=%.0f)", currentFile, smoothedRMS);
                }
                silenceMs = 0;

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
            } else if (voiceActive) {
                silenceMs += 30;

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

                if (silenceMs >= 1500) {
                    voiceActive = false;
                    bgCount = 0;
                    bgIndex = 0;
                    
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
                snprintf(currentFile, sizeof(currentFile), "/lifelog/rec_%05lu.opus", fileIndex++);
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

// ── Writer task ────────────────────────────────────────────────────

// Write callback for oggz
static size_t writeCallback(void *user_handle, void *buf, size_t n) {
    File *file = (File*)user_handle;
    return file->write((uint8_t*)buf, n);
}

void writerTask(void *pvParameters) {
    File activeFile;
    uint32_t totalEncoded = 0;
    char currentFilename[64] = {0};
    
    delay(1000);
    
    while (true) {
        AudioChunkMsg msg;
        if (xQueueReceive(audioQueue, &msg, portMAX_DELAY)) {
            // Open new file if needed
            if (currentFilename[0] == '\0' || strcmp(currentFilename, msg.filename) != 0) {
                if (activeFile) {
                    #ifdef AUDIO_FORMAT_WAV
                    // WAV: just close, header written at end
                    activeFile.flush();
                    delay(200);
                    activeFile.close();
                    delay(200);
                    LOG("[WRITER] Closed %s", currentFilename);
                    #else
                    // Opus: flush Ogg and close
                    flushOggz(oggz);
                    oggz_close(oggz);
                    oggz = NULL;
                    activeFile.flush();
                    delay(200);
                    activeFile.close();
                    delay(200);
                    LOG("[WRITER] Closed %s", currentFilename);
                    #endif
                    
                    if (WiFi.status() == WL_CONNECTED && totalEncoded > 0) {
                        delay(100);
                        uploadFile(currentFilename);
                        delay(200);
                        SD.remove(currentFilename);
                        LOG("[WRITER] Uploaded %s", currentFilename);
                    }
                    totalEncoded = 0;
                }
                
                // Open new file
                strncpy(currentFilename, msg.filename, sizeof(currentFilename));
                activeFile = SD.open(currentFilename, FILE_WRITE);
                if (activeFile) {
                    #ifdef AUDIO_FORMAT_WAV
                    // WAV: write placeholder header (updated at end)
                    writeWavHeader(activeFile, 0);
                    LOG("[WRITER] Opened %s (WAV)", currentFilename);
                    #else
                    // Opus: create oggz handle
                    oggz = oggz_new(OGGZ_WRITE | OGGZ_NONSTRICT);
                    if (oggz) {
                        oggzSerialno = oggz_serialno_new(oggz);
                        oggz_io_set_write(oggz, writeCallback, &activeFile);
                        writeOpusHeaders(oggz, oggzSerialno);
                        LOG("[WRITER] Opened %s", currentFilename);
                    }
                    #endif
                } else {
                    LOG("[WRITER] Failed to open %s", currentFilename);
                    currentFilename[0] = '\0';
                }
            }
            
            // Encode and write audio data
            #ifdef AUDIO_FORMAT_WAV
            // WAV: write raw PCM
            if (activeFile && msg.samples > 0) {
                activeFile.write((uint8_t*)msg.data, msg.samples * 2);
                totalEncoded += msg.samples * 2;
            }
            #else
            // Opus: encode and write
            if (oggz && msg.samples > 0) {
                uint8_t opusBuffer[1024];
                uint32_t pcmIndex = 0;
                
                while (pcmIndex < msg.samples) {
                    int samplesAvailable = msg.samples - pcmIndex;
                    int samplesToEncode = (samplesAvailable < OPUS_FRAME_SIZE) ? samplesAvailable : OPUS_FRAME_SIZE;
                    
                    int16_t encodeBuffer[OPUS_FRAME_SIZE];
                    memcpy(encodeBuffer, msg.data + pcmIndex, samplesToEncode * 2);
                    if (samplesToEncode < OPUS_FRAME_SIZE) {
                        memset(encodeBuffer + samplesToEncode, 0, (OPUS_FRAME_SIZE - samplesToEncode) * 2);
                    }
                    
                    int bytesEncoded = opus_encode(opusEncoder, encodeBuffer, OPUS_FRAME_SIZE,
                                                   opusBuffer, sizeof(opusBuffer));
                    
                    if (bytesEncoded > 0) {
                        writeOpusFrame(oggz, oggzSerialno, opusBuffer, bytesEncoded, OPUS_FRAME_SIZE);
                        totalEncoded += bytesEncoded;
                    }
                    pcmIndex += samplesToEncode;
                }
                
                flushOggz(oggz);
            }
            #endif
            
            // End of utterance
            if (msg.isEnd) {
                #ifdef AUDIO_FORMAT_WAV
                // WAV: update header with final size
                if (activeFile) {
                    updateWavHeader(activeFile, totalEncoded);
                    activeFile.flush();
                    delay(200);
                    activeFile.close();
                    delay(200);
                    LOG("[WRITER] Closed %s (%d bytes WAV)", currentFilename, totalEncoded);
                    
                    if (WiFi.status() == WL_CONNECTED && totalEncoded > 0) {
                        delay(100);
                        uploadFile(currentFilename);
                        delay(200);
                        SD.remove(currentFilename);
                        LOG("[WRITER] Uploaded %s", currentFilename);
                    }
                    totalEncoded = 0;
                }
                #else
                // Opus: flush and close
                if (oggz) {
                    flushOggz(oggz);
                    oggz_close(oggz);
                    oggz = NULL;
                }
                if (activeFile) {
                    activeFile.flush();
                    delay(200);
                    activeFile.close();
                    delay(200);
                    LOG("[WRITER] Closed %s (%d bytes)", currentFilename, totalEncoded);
                    
                    if (WiFi.status() == WL_CONNECTED && totalEncoded > 0) {
                        delay(100);
                        uploadFile(currentFilename);
                        delay(200);
                        SD.remove(currentFilename);
                        LOG("[WRITER] Uploaded %s", currentFilename);
                    }
                    totalEncoded = 0;
                }
                #endif
                currentFilename[0] = '\0';
            }
            
            free(msg.data);
        }
    }
}
