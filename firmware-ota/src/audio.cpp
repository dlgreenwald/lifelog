#include "audio.h"
#include "config.h"
#include "upload.h"
#include <I2S.h>
#include <WiFi.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"

// WAV header size
#define WAV_HEADER_SIZE 44
#define SAMPLE_BITS 16
#define VOLUME_GAIN 3

// Queue for audio chunks
#define AUDIO_QUEUE_SIZE 10
static QueueHandle_t audioQueue = NULL;

// Global state
volatile bool recording = false;
volatile bool vadMode = true;
uint32_t fileIndex = 0;
uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};

// Chunk message
typedef struct {
    uint8_t* data;
    uint32_t size;
    bool isEnd;
    char filename[64];
} AudioChunkMsg;

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
    audioQueue = xQueueCreate(AUDIO_QUEUE_SIZE, sizeof(AudioChunkMsg));
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
    I2S.setAllPins(-1, 42, 41, -1, -1);
    if (!I2S.begin(PDM_MONO_MODE, SAMPLE_RATE, SAMPLE_BITS)) {
        LOG_I2S(LOG_ERROR, "Failed to initialize I2S!");
        return;
    }
    LOG_I2S(LOG_INFO, "PDM Mic ready (CLK=42, DIN=41)");

    // Allocate A/B buffers in PSRAM
    uint32_t bufBytes = (SAMPLE_RATE * SAMPLE_BITS / 8) * 5;
    bufA = (int16_t*)ps_malloc(bufBytes);
    bufB = (int16_t*)ps_malloc(bufBytes);
    if (!bufA || !bufB) {
        LOG_AUDIO(LOG_ERROR, "PSRAM malloc failed");
        return;
    }
    bufCapacity = bufBytes / 2;
    audioBuf = bufA;
    writeBuf = bufB;
    audioCount = 0;
    writeCount = 0;
    writeDone = true;
    LOG_AUDIO(LOG_INFO, "A/B buffers ready (%d samples each)", bufCapacity);

    // VAD state
    bool voiceActive = false;
    uint32_t silenceMs = 0;
    float startThreshold = VAD_THRESHOLD;
    uint32_t startTime = millis();
    uint32_t startupGraceMs = 2000;

    // RMS analysis
    int analysisCapacity = VAD_ANALYSIS_MS * SAMPLE_RATE / 1000;
    int16_t* analysisBuffer = (int16_t*)ps_malloc(analysisCapacity * 2);
    int analysisIndex = 0;
    float smoothedRMS = 0;

    // Median filter
    #define MEDIAN_SAMPLES 5
    float rmsHistory[MEDIAN_SAMPLES] = {0};
    int rmsIndex = 0;
    int rmsCount = 0;

    while (true) {
        // ALWAYS read from I2S — never block
        int samplesToRead = SAMPLE_RATE * VAD_CHUNK_MS / 1000;
        int16_t readBuffer[480];
        size_t bytesRead = 0;
        esp_i2s::i2s_read(esp_i2s::I2S_NUM_0, readBuffer, samplesToRead * 2, &bytesRead, portMAX_DELAY);
        if (bytesRead == 0) continue;

        int samplesRead = bytesRead / 2;

        // Compute RMS on RAW audio (before gain) for VAD
        int available = analysisCapacity - analysisIndex;
        int toCopy = (samplesRead < available) ? samplesRead : available;
        memcpy(analysisBuffer + analysisIndex, readBuffer, toCopy * 2);
        analysisIndex += toCopy;

        // Apply volume gain ONLY to recording buffer
        for (int i = 0; i < samplesRead; i++) {
            (*(uint16_t*)(readBuffer + i)) <<= VOLUME_GAIN;
        }

        // Only buffer when recording
        if (recording) {
            // Flush when buffer full
            if (audioCount + samplesRead > bufCapacity) {
                while (!writeDone) { vTaskDelay(pdMS_TO_TICKS(5)); }
                int16_t* tmp = writeBuf;
                writeBuf = audioBuf;
                writeCount = audioCount;
                audioBuf = tmp;
                audioCount = 0;
                bufferReady = true;
                writeDone = false;
            }

            memcpy(audioBuf + audioCount, readBuffer, bytesRead);
            audioCount += samplesRead;
        }

        if (analysisIndex >= analysisCapacity) {
            smoothedRMS = computeRMS(analysisBuffer, analysisCapacity);
            analysisIndex = 0;

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
                LOG_VAD(LOG_DEBUG, "RMS=%.0f, median=%.0f", smoothedRMS, medianRMS);
                lastRecLog = now;
            }

            // VAD logic — use median for robustness against spikes
            if (!voiceActive && medianRMS > startThreshold && (millis() - startTime) > startupGraceMs) {
                voiceActive = true;
                silenceMs = 0;
                audioCount = 0;
                recording = true;
                LOG_VAD(LOG_INFO, "Voice started (median=%.0f, start=%.0f)", medianRMS, startThreshold);
            } else if (voiceActive) {
                if (medianRMS > startThreshold) {
                    silenceMs = 0;
                } else {
                    silenceMs += VAD_CHUNK_MS;
                }

                // Log RMS silence periodically
                static uint32_t lastRecLog = 0;
                uint32_t now = millis();
                if (now - lastRecLog >= 1000) {
                    LOG_VAD(LOG_DEBUG, "silence=%d ms / %d", silenceMs, VAD_SILENCE_MS);
                    lastRecLog = now;
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
                    } else {
                        audioCount = 0;
                    }
                    LOG_VAD(LOG_INFO, "Voice ended (silence %d ms)", silenceMs);
                    lastRecLog = 0;
                    // Reset median filter so next recording starts fresh
                    memset(rmsHistory, 0, sizeof(rmsHistory));
                    rmsIndex = 0;
                    rmsCount = 0;
                }
            }
        }
    }
}

// ── Write task (reads PSRAM, writes SD, uploads) ──────────────────

void writerTask(void *pvParameters) {
    while (true) {
        if (!bufferReady) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        // Write the ready buffer to SD
        uint32_t samplesToWrite = writeCount;
        uint32_t totalBytes = samplesToWrite * 2;

        char filename[64];
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);

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

        bufferReady = false;
        writeDone = true;
    }
}
