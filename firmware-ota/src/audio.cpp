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
#define VOLUME_GAIN 2

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

// ── Audio capture task (matches guide approach) ────────────────────

void audioTask(void *pvParameters) {
    // Initialize I2S like the guide
    I2S.setAllPins(-1, 42, 41, -1, -1);
    if (!I2S.begin(PDM_MONO_MODE, SAMPLE_RATE, SAMPLE_BITS)) {
        LOG("[I2S] Failed to initialize I2S!");
        return;
    }
    LOG("[I2S] PDM Mic ready (CLK=42, DIN=41)");

    LOG("[AUDIO] Ready for recording");

    while (true) {
        if (!recording) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        // Record to PSRAM buffer (like the guide)
        uint32_t record_size = (SAMPLE_RATE * SAMPLE_BITS / 8) * (recordDurationMs / 1000);
        uint8_t *rec_buffer = (uint8_t *)ps_malloc(record_size);
        if (!rec_buffer) {
            LOG("[AUDIO] PSRAM malloc failed");
            recording = false;
            continue;
        }
        LOG("[AUDIO] Recording %d seconds (%d bytes)...", recordDurationMs / 1000, record_size);

        // Read from I2S into buffer (like the guide)
        uint32_t sample_size = 0;
        esp_i2s::i2s_read(esp_i2s::I2S_NUM_0, rec_buffer, record_size, &sample_size, portMAX_DELAY);

        if (sample_size == 0) {
            LOG("[AUDIO] Record failed");
            free(rec_buffer);
            recording = false;
            continue;
        }
        LOG("[AUDIO] Recorded %d bytes", sample_size);

        // Apply volume gain (like the guide)
        for (uint32_t i = 0; i < sample_size; i += SAMPLE_BITS / 8) {
            (*(uint16_t *)(rec_buffer + i)) <<= VOLUME_GAIN;
        }

        // Write WAV to SD (like the guide)
        char filename[64];
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);

        File file = SD.open(filename, FILE_WRITE);
        if (!file) {
            LOG("[AUDIO] Failed to open %s", filename);
            free(rec_buffer);
            recording = false;
            continue;
        }

        // Write WAV header
        uint8_t wav_header[WAV_HEADER_SIZE];
        generate_wav_header(wav_header, record_size, SAMPLE_RATE);
        file.write(wav_header, WAV_HEADER_SIZE);

        // Write audio data
        LOG("[AUDIO] Writing %d bytes to %s...", record_size, filename);
        if (file.write(rec_buffer, record_size) != record_size) {
            LOG("[AUDIO] Write failed!");
        } else {
            LOG("[AUDIO] Saved: %s (%d bytes)", filename, record_size + WAV_HEADER_SIZE);
            strncpy(lastSavedFile, filename, sizeof(lastSavedFile));
        }

        free(rec_buffer);
        file.close();
        LOG("[AUDIO] Recording complete");

        recording = false;
    }
}

// ── Writer task (not used in WAV mode) ─────────────────────────────

void writerTask(void *pvParameters) {
    // WAV mode doesn't use the writer task
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
