#include "audio.h"
#include "config.h"
#include "upload.h"
#include <opus.h>

// Opus encoder state
static OpusEncoder* opusEncoder = NULL;
static uint8_t opusBuffer[1024];
static int16_t encodeBuffer[OPUS_FRAME_SIZE];

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

static uint32_t flushOpusToFile(File& file, int16_t* buffer, uint32_t samples) {
    uint32_t totalEncoded = 0;
    uint32_t pcmIndex = 0;

    while (pcmIndex < samples) {
        int samplesAvailable = samples - pcmIndex;
        int samplesToEncode = (samplesAvailable < OPUS_FRAME_SIZE) ? samplesAvailable : OPUS_FRAME_SIZE;

        memcpy(encodeBuffer, buffer + pcmIndex, samplesToEncode * 2);
        if (samplesToEncode < OPUS_FRAME_SIZE) {
            memset(encodeBuffer + samplesToEncode, 0, (OPUS_FRAME_SIZE - samplesToEncode) * 2);
        }

        int bytesEncoded = opus_encode(opusEncoder, encodeBuffer, OPUS_FRAME_SIZE,
                                       opusBuffer, sizeof(opusBuffer));

        if (bytesEncoded > 0) {
            uint16_t frameLen = (uint16_t)bytesEncoded;
            file.write((uint8_t*)&frameLen, 2);
            file.write(opusBuffer, bytesEncoded);
            totalEncoded += bytesEncoded + 2;
        }
        pcmIndex += samplesToEncode;
    }
    return totalEncoded;
}

// ── Public API ─────────────────────────────────────────────────────

void audioInit() {
    // Mic and encoder are initialized in the task
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

// ── Main task ──────────────────────────────────────────────────────

void audioTask(void *pvParameters) {
    // Allocate chunk buffer
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
    uint32_t totalEncoded = 0;
    uint32_t startMs = 0;
    File activeFile;

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
        if (!recording) {
            if (activeFile) {
                if (captured > 0) {
                    totalEncoded += flushOpusToFile(activeFile, chunkBuffer, captured);
                    captured = 0;
                }
                activeFile.close();
                LOG("[AUDIO] Closed file (%d bytes opus)", totalEncoded);
            }
            voiceActive = false;
            silenceMs = 0;
            captured = 0;
            totalEncoded = 0;
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        // Read audio chunk
        int chunkSamples = VAD_CHUNK_MS * SAMPLE_RATE / 1000;
        int16_t readBuffer[480];
        size_t bytesRead = 0;
        esp_err_t err = i2s_read(I2S_NUM_0, readBuffer, chunkSamples * 2, &bytesRead, pdMS_TO_TICKS(100));
        if (err != ESP_OK || bytesRead == 0) continue;
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

                // Log idle status periodically
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
                    totalEncoded = 0;
                    startMs = millis();
                    char filename[64];
                    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", fileIndex++);
                    snprintf(lastSavedFile, sizeof(lastSavedFile), "%s", filename);
                    activeFile = SD.open(filename, FILE_WRITE);
                    if (!activeFile) { LOG("[VAD] Failed to open %s", filename); recording = false; continue; }
                    LOG("[VAD] Voice started — %s (RMS=%.0f)", filename, smoothedRMS);
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
                    totalEncoded += flushOpusToFile(activeFile, chunkBuffer, captured);
                    captured = 0;
                }
            } else if (voiceActive) {
                silenceMs += VAD_CHUNK_MS;
                if (captured + samplesRead <= CHUNK_SAMPLES) {
                    memcpy(chunkBuffer + captured, readBuffer, bytesRead);
                    captured += samplesRead;
                }
                if (captured + samplesRead > CHUNK_SAMPLES) {
                    totalEncoded += flushOpusToFile(activeFile, chunkBuffer, captured);
                    captured = 0;
                }
                if (silenceMs >= VAD_SILENCE_MS) {
                    voiceActive = false;
                    bgCount = 0;
                    bgIndex = 0;
                    if (captured > 0) {
                        totalEncoded += flushOpusToFile(activeFile, chunkBuffer, captured);
                        captured = 0;
                    }
                    activeFile.close();
                    LOG("[VAD] Voice ended (%d ms, %d bytes)", millis() - startMs, totalEncoded);
                    if (WiFi.status() == WL_CONNECTED && totalEncoded > 0) {
                        uploadFile(lastSavedFile);
                        SD.remove(lastSavedFile);
                        LOG("[VAD] Uploaded %s", lastSavedFile);
                    }
                    totalEncoded = 0;
                    silenceMs = 0;
                }
            }
        } else {
            // Fixed duration mode
            if (captured == 0 && !activeFile) {
                startMs = millis();
                char filename[64];
                snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", fileIndex++);
                activeFile = SD.open(filename, FILE_WRITE);
                if (!activeFile) { LOG("[AUDIO] Failed to open %s", filename); recording = false; continue; }
                LOG("[AUDIO] Recording to %s", filename);
            }
            if (captured + samplesRead <= CHUNK_SAMPLES) {
                memcpy(chunkBuffer + captured, readBuffer, bytesRead);
                captured += samplesRead;
            }
            if (captured + samplesRead > CHUNK_SAMPLES) {
                totalEncoded += flushOpusToFile(activeFile, chunkBuffer, captured);
                captured = 0;
            }
            uint32_t elapsed = millis() - startMs;
            if (elapsed >= recordDurationMs) {
                if (captured > 0) {
                    totalEncoded += flushOpusToFile(activeFile, chunkBuffer, captured);
                    captured = 0;
                }
                activeFile.close();
                LOG("[AUDIO] Saved (%d ms, %d bytes)", elapsed, totalEncoded);
                totalEncoded = 0;
                recording = false;
            }
        }
    }
}
