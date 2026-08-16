#include "audio.h"
#include "config.h"
#include "upload.h"
#include <I2S.h>
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
    LOG("[VAD] Mode: %s", vadMode ? "VAD (auto)" : "Fixed duration");
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

// ── Audio capture task with VAD trigger ────────────────────────────

void audioTask(void *pvParameters) {
    I2S.setAllPins(-1, 42, 41, -1, -1);
    if (!I2S.begin(PDM_MONO_MODE, SAMPLE_RATE, SAMPLE_BITS)) {
        LOG("[I2S] Failed to initialize I2S!");
        return;
    }
    LOG("[I2S] PDM Mic ready (CLK=42, DIN=41)");

    // Allocate A/B buffers in PSRAM
    uint32_t bufBytes = (SAMPLE_RATE * SAMPLE_BITS / 8) * 5;  // 5 seconds each
    bufA = (int16_t*)ps_malloc(bufBytes);
    bufB = (int16_t*)ps_malloc(bufBytes);
    if (!bufA || !bufB) {
        LOG("[AUDIO] PSRAM malloc failed");
        return;
    }
    bufCapacity = bufBytes / 2;
    audioBuf = bufA;
    writeBuf = bufB;
    audioCount = 0;
    writeCount = 0;
    writeDone = true;
    LOG("[AUDIO] A/B buffers ready (%d samples each)", bufCapacity);

    // VAD state
    bool voiceActive = false;
    uint32_t silenceMs = 0;
    float bgNoise = 200;
    float currentThreshold = VAD_THRESHOLD;

    // RMS analysis
    int analysisCapacity = VAD_ANALYSIS_MS * SAMPLE_RATE / 1000;
    int16_t* analysisBuffer = (int16_t*)ps_malloc(analysisCapacity * 2);
    int analysisIndex = 0;
    float smoothedRMS = 0;

    while (true) {
        // Always read from I2S
        int samplesToRead = SAMPLE_RATE * VAD_CHUNK_MS / 1000;
        int16_t readBuffer[480];
        size_t bytesRead = 0;
        esp_i2s::i2s_read(esp_i2s::I2S_NUM_0, readBuffer, samplesToRead * 2, &bytesRead, portMAX_DELAY);
        if (bytesRead == 0) continue;

        int samplesRead = bytesRead / 2;

        // Apply volume gain
        for (int i = 0; i < samplesRead; i++) {
            (*(uint16_t*)(readBuffer + i)) <<= VOLUME_GAIN;
        }

        // Compute RMS for VAD
        int available = analysisCapacity - analysisIndex;
        int toCopy = (samplesRead < available) ? samplesRead : available;
        memcpy(analysisBuffer + analysisIndex, readBuffer, toCopy * 2);
        analysisIndex += toCopy;

        if (analysisIndex >= analysisCapacity) {
            smoothedRMS = computeRMS(analysisBuffer, analysisCapacity);
            analysisIndex = 0;

            // Update background noise when idle
            if (!recording) {
                bgNoise = bgNoise * 0.95f + smoothedRMS * 0.05f;
                currentThreshold = max(bgNoise * 1.5f, (float)VAD_THRESHOLD);
            }
        }

        // VAD: detect speech to trigger recording
        if (smoothedRMS > currentThreshold) {
            if (!recording && !voiceActive) {
                voiceActive = true;
                silenceMs = 0;
                audioCount = 0;
                recording = true;
                LOG("[VAD] Voice started (RMS=%.0f, thresh=%.0f)", smoothedRMS, currentThreshold);
            }
            silenceMs = 0;
        } else if (voiceActive) {
            silenceMs += VAD_CHUNK_MS;
            if (silenceMs >= VAD_SILENCE_MS) {
                voiceActive = false;
                recording = false;
                LOG("[VAD] Voice ended (silence %d ms)", silenceMs);
            }
        }

        // Buffer audio when recording
        if (recording) {
            if (audioCount + samplesRead <= bufCapacity) {
                memcpy(audioBuf + audioCount, readBuffer, bytesRead);
                audioCount += samplesRead;
            }

            // Swap when buffer full
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

            // Write audio data (gain already applied during capture)
            file.write((uint8_t*)writeBuf, totalBytes);
            file.flush();  // Ensure all data written to SD
            file.close();
            LOG("[AUDIO] Saved: %s (%d bytes)", filename, totalBytes + WAV_HEADER_SIZE);

            // Auto-upload
            if (WiFi.status() == WL_CONNECTED) {
                LOG("[AUDIO] Uploading %s...", filename);
                if (uploadFile(filename)) {
                    SD.remove(filename);
                    LOG("[AUDIO] Uploaded and deleted %s", filename);
                }
            }
        } else {
            LOG("[AUDIO] Failed to open %s", filename);
        }

        bufferReady = false;
        writeDone = true;
    }
}
