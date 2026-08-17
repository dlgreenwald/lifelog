#include "audio.h"
#include "config.h"
#include "upload.h"
#include "driver/i2s.h"
#include <WiFi.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"

// WAV header size
#define WAV_HEADER_SIZE 44
#define SAMPLE_BITS 16
#define VOLUME_GAIN 3

// Global state
volatile bool recording = false;
volatile bool vadMode = true;
volatile bool sdBusy = false;
uint32_t fileIndex = 0;
uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};
static TaskHandle_t writerTaskHandle = NULL;

// ── Buffer health counters ────────────────────────────────────────
static uint32_t writerStallCount = 0;   // Times audioTask waited for writer
static uint32_t writerStallMaxMs = 0;   // Longest stall duration
static uint32_t dmaPartialCount = 0;    // i2s_read returned < requested
static uint32_t flushDropCount = 0;     // End-of-recording buffer discarded
static uint32_t totalSamplesCaptured = 0; // Total I2S samples read
static uint32_t totalSamplesWritten = 0;  // Total samples written to SD

uint32_t getWriterStallCount() { return writerStallCount; }
uint32_t getWriterStallMaxMs() { return writerStallMaxMs; }
uint32_t getDmaPartialCount() { return dmaPartialCount; }
uint32_t getFlushDropCount() { return flushDropCount; }
uint32_t getTotalSamplesCaptured() { return totalSamplesCaptured; }
uint32_t getTotalSamplesWritten() { return totalSamplesWritten; }

// ── WAV header (from Seeed Studio guide) ───────────────────────────

static void generate_wav_header(uint8_t *wav_header, uint32_t wav_size, uint32_t sample_rate) {
    uint32_t file_size = wav_size + WAV_HEADER_SIZE - 8;
    uint32_t byte_rate = SAMPLE_RATE * SAMPLE_BITS / 8;
    
    const uint8_t set_wav_header[] = {
        'R', 'I', 'F', 'F', // ChunkID
        file_size, file_size >> 8, file_size >> 16, file_size >> 24, // ChunkSize
        'W', 'A', 'V', 'E', // Format
        'f', 'm', 't', ' ', // Subchunk1ID
        0x10, 0, 0, 0, // Subchunk1Size (16 for PCM)
        0x01, 0, // AudioFormat (PCM)
        0x01, 0, // NumChannels (mono)
        sample_rate, sample_rate >> 8, sample_rate >> 16, sample_rate >> 24, // SampleRate
        byte_rate, byte_rate >> 8, byte_rate >> 16, byte_rate >> 24, // ByteRate
        0x02, 0, // BlockAlign
        0x10, 0, // BitsPerSample
        'd', 'a', 't', 'a', // Subchunk2ID
        wav_size, wav_size >> 8, wav_size >> 16, wav_size >> 24 // Subchunk2Size
    };
    
    memcpy(wav_header, set_wav_header, WAV_HEADER_SIZE);
}

// ── RMS computation for VAD ────────────────────────────────────────

static float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

// ── Public API ─────────────────────────────────────────────────────

void audioInit() {
    // No queue needed — A/B buffers + task notifications handle data flow
}

void setWriterTaskHandle(TaskHandle_t handle) {
    writerTaskHandle = handle;
}

void startRecording(uint32_t durationMs) {
    if (recording) return;
    recordDurationMs = durationMs;
    recording = true;
}

void toggleVAD() {
    vadMode = !vadMode;
    LOG_VAD(LOG_INFO, "Mode: %s", vadMode ? "VAD (auto)" : "Fixed duration");
}

// ── A/B Buffer State ───────────────────────────────────────────────

static int16_t* bufA = NULL;
static int16_t* bufB = NULL;
static int16_t* audioBuf = NULL;   // Buffer audio task writes to
static int16_t* writeBuf = NULL;   // Buffer write task reads from
static uint32_t audioCount = 0;    // Samples in audio buffer
static uint32_t writeCount = 0;    // Samples in write buffer
static volatile bool bufferReady = false;  // Audio buffer full
static volatile bool writeDone = true;     // Write task idle
static uint32_t bufCapacity = 0;   // Max samples per buffer

// ── Audio capture task with VAD (records continuously) ─────────────

void audioTask(void *pvParameters) {
    // Direct I2S driver — PDM CLK maps to bck_io_num, DIN to data_in_num
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = 1024,  // ESP-IDF max; 4 × 1024 = 4096 samples = 256ms ring buffer
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0,
        .mclk_multiple = I2S_MCLK_MULTIPLE_DEFAULT,
        .bits_per_chan = I2S_BITS_PER_CHAN_DEFAULT,
    };
    i2s_pin_config_t pin_config = {
        .mck_io_num = I2S_PIN_NO_CHANGE,
        .bck_io_num = I2S_PIN_NO_CHANGE,
        .ws_io_num = I2S_MIC_CLK,    // PDM CLK = GPIO42 (mapped via fsPin)
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = I2S_MIC_DIN,  // PDM DIN = GPIO41
    };
    esp_err_t err = i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
    if (err != ESP_OK) {
        LOG_I2S(LOG_ERROR, "i2s_driver_install failed: %d", err);
        return;
    }
    err = i2s_set_pin(I2S_NUM_0, &pin_config);
    if (err != ESP_OK) {
        LOG_I2S(LOG_ERROR, "i2s_set_pin failed: %d", err);
        return;
    }
    i2s_set_clk(I2S_NUM_0, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
    LOG_I2S(LOG_INFO, "PDM Mic ready (CLK=42, DIN=41) — DMA: 4 × 1024 samples");

    // Allocate A/B buffers in PSRAM — 5 seconds each
    // Multiple 200ms DMA reads accumulate before each swap/save
    uint32_t bufBytes = (SAMPLE_RATE * SAMPLE_BITS / 8) * 5;
    bufA = (int16_t*)ps_malloc(bufBytes);
    bufB = (int16_t*)ps_malloc(bufBytes);
    if (!bufA || !bufB) {
        LOG_AUDIO(LOG_ERROR, "PSRAM malloc failed");
        return;
    }
    bufCapacity = bufBytes / sizeof(int16_t);
    audioBuf = bufA;
    writeBuf = bufB;
    audioCount = 0;
    writeCount = 0;
    writeDone = true;
    LOG_AUDIO(LOG_INFO, "A/B buffers ready (%d samples each)", bufCapacity);

    // VAD state
    bool voiceActive = false;
    uint32_t silenceStartMs = 0;  // millis() when silence began
    float startThreshold = VAD_THRESHOLD;
    uint32_t startTime = millis();
    uint32_t startupGraceMs = 2000;

    // RMS analysis — 200ms DMA-aligned reads (no accumulation needed)
    int analysisCapacity = SAMPLE_RATE * VAD_ANALYSIS_MS / 1000;  // 3200 samples
    int16_t* analysisBuffer = (int16_t*)ps_malloc(analysisCapacity * sizeof(int16_t));
    if (!analysisBuffer) {
        LOG_AUDIO(LOG_ERROR, "Analysis buffer PSRAM malloc failed");
        return;
    }
    float smoothedRMS = 0;

    // Median filter
    #define MEDIAN_SAMPLES 5
    float rmsHistory[MEDIAN_SAMPLES] = {0};
    int rmsIndex = 0;
    int rmsCount = 0;

    while (true) {
        // DMA fill: CPU sleeps until 3200 samples available in ring buffer
        size_t bytesRead = 0;
        i2s_read(I2S_NUM_0, analysisBuffer, analysisCapacity * sizeof(int16_t),
                 &bytesRead, portMAX_DELAY);
        if (bytesRead == 0) continue;

        int samplesRead = bytesRead / 2;
        uint32_t expectedBytes = analysisCapacity * sizeof(int16_t);
        if (bytesRead < expectedBytes) {
            dmaPartialCount++;
            LOG_AUDIO(LOG_WARN, "DMA partial read: %d/%d bytes (overflow likely)",
                      (int)bytesRead, (int)expectedBytes);
        }

        // Compute RMS on RAW audio (before gain) for VAD
        smoothedRMS = computeRMS(analysisBuffer, samplesRead);

        // Apply volume gain in-place (recording path uses this buffer)
        for (int i = 0; i < samplesRead; i++) {
            analysisBuffer[i] <<= VOLUME_GAIN;
        }

        // Copy gain-applied audio to recording buffer
        if (recording) {
            // Flush when buffer full
            if (audioCount + samplesRead > bufCapacity) {
                uint32_t waitStart = millis();
                while (!writeDone) { vTaskDelay(pdMS_TO_TICKS(5)); }
                uint32_t waitMs = millis() - waitStart;
                if (waitMs > 0) {
                    writerStallCount++;
                    if (waitMs > writerStallMaxMs) writerStallMaxMs = waitMs;
                    LOG_AUDIO(LOG_WARN, "Writer stall: waited %lu ms", (unsigned long)waitMs);
                }
                int16_t* tmp = writeBuf;
                writeBuf = audioBuf;
                writeCount = audioCount;
                audioBuf = tmp;
                audioCount = 0;
                bufferReady = true;
                writeDone = false;
                if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
            }

            memcpy(audioBuf + audioCount, analysisBuffer, bytesRead);
            audioCount += samplesRead;
            totalSamplesCaptured += samplesRead;
        }

        // Median filter
        rmsHistory[rmsIndex] = smoothedRMS;
        rmsIndex = (rmsIndex + 1) % MEDIAN_SAMPLES;
        if (rmsCount < MEDIAN_SAMPLES) rmsCount++;

        float sorted[MEDIAN_SAMPLES];
        memcpy(sorted, rmsHistory, rmsCount * sizeof(float));
        for (int i = 0; i < rmsCount - 1; i++) {
            for (int j = i + 1; j < rmsCount; j++) {
                if (sorted[i] > sorted[j]) {
                    float tmp = sorted[i];
                    sorted[i] = sorted[j];
                    sorted[j] = tmp;
                }
            }
        }
        float medianRMS = sorted[rmsCount / 2];

        // Log RMS periodically
        static uint32_t lastRecLog = 0;
        uint32_t now = millis();
        if (now - lastRecLog >= 1000) {
            LOG_VAD(LOG_INFO, "RMS=%.0f, median=%.0f", smoothedRMS, medianRMS);
            lastRecLog = now;
        }

        // VAD logic — use median for robustness against spikes
        if (!voiceActive && medianRMS > startThreshold && (now - startTime) > startupGraceMs) {
            voiceActive = true;
            silenceStartMs = now;  // reset silence tracker
            audioCount = 0;
            recording = true;
            LOG_VAD(LOG_INFO, "Voice started (median=%.0f, start=%.0f)", medianRMS, startThreshold);
        } else if (voiceActive) {
            if (medianRMS > startThreshold) {
                silenceStartMs = now;  // voice still present — reset silence timer
            }

            uint32_t silenceMs = now - silenceStartMs;

            // Log RMS silence periodically
            static uint32_t lastSilenceLog = 0;
            if (now - lastSilenceLog >= 1000) {
                LOG_VAD(LOG_INFO, "silence=%d ms / %d", silenceMs, VAD_SILENCE_MS);
                lastSilenceLog = now;
            }

            if (silenceMs >= VAD_SILENCE_MS) {
                voiceActive = false;
                recording = false;
                // Flush remaining partial buffer
                if (audioCount > 0 && writeDone) {
                    int16_t* tmp = writeBuf;
                    writeBuf = audioBuf;
                    writeCount = audioCount;
                    audioBuf = tmp;
                    audioCount = 0;
                    bufferReady = true;
                    writeDone = false;
                    if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
                } else {
                    if (audioCount > 0) {
                        flushDropCount++;
                        LOG_AUDIO(LOG_WARN, "Flush drop: %lu samples discarded (writeDone=%d)",
                                  (unsigned long)audioCount, (int)writeDone);
                    }
                    audioCount = 0;
                }
                LOG_VAD(LOG_INFO, "Voice ended (silence %d ms)", silenceMs);
                lastRecLog = 0;
                // Keep median filter state — don't reset between recordings
            }
        }
    }
}

// ── Write task (reads PSRAM, writes SD, uploads) ──────────────────

void writerTask(void *pvParameters) {
    while (true) {
        // Block until audio task signals a buffer is ready
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        // Write the ready buffer to SD
        uint32_t samplesToWrite = writeCount;
        totalSamplesWritten += samplesToWrite;
        uint32_t totalBytes = samplesToWrite * 2;

        char filename[64];
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);

        sdBusy = true;
        File file = SD.open(filename, FILE_WRITE);
        if (file) {
            uint8_t wav_header[WAV_HEADER_SIZE];
            generate_wav_header(wav_header, totalBytes, SAMPLE_RATE);
            file.write(wav_header, WAV_HEADER_SIZE);

            file.write((uint8_t*)writeBuf, totalBytes);
            file.flush();
            delay(150);  // Let SD card complete write
            file.close();
            delay(150);  // Wait after close
            LOG_AUDIO(LOG_INFO, "Saved: %s (%d bytes)", filename, totalBytes + WAV_HEADER_SIZE);

            if (WiFi.status() == WL_CONNECTED) {
                delay(100);  // Pause before upload
                LOG_AUDIO(LOG_INFO, "Uploading %s...", filename);
                if (uploadFile(filename)) {
                    delay(300);  // Wait after upload
                    SD.remove(filename);
                    LOG_AUDIO(LOG_INFO, "Uploaded and deleted %s", filename);
                }
            }
        } else {
            LOG_AUDIO(LOG_ERROR, "Failed to open %s", filename);
        }
        sdBusy = false;

        bufferReady = false;
        writeDone = true;
    }
}
