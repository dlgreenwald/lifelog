// Audio — ring buffer + producer (AFE feeds ring, writer drains it)
// I2S/AFE tasks in i2s_fe.cpp, Opus/writer in writer.cpp.

#include "audio.h"
#include "config.h"
#include "i2s_fe.h"
#include "writer.h"

static const char* TAG = "AUDIO";

// ── Global state ──────────────────────────────────────────────────
volatile bool recording = false;
volatile bool vadMode = true;

// Audio activity (set by i2s_fe.cpp on voice-start/voice-end, read by ledLoop())
volatile AudioActivity audioActivity = AUDIO_IDLE;
unsigned long listenStartMs = 0;

SemaphoreHandle_t sdMutex = NULL;
static uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};
TaskHandle_t writerTaskHandle = NULL;

// Utterance tracking
volatile uint32_t utteranceId = 0;
volatile uint32_t chunkIndex = 0;
volatile bool isFinal = false;

// Ring buffer
RingbufHandle_t audioRingBuf = NULL;

// ── Buffer health counters ────────────────────────────────────────
static uint32_t writerStallCount = 0;   // Times audioTask waited for writer
static uint32_t writerStallMaxMs = 0;   // Longest stall duration
uint32_t flushDropCount = 0;            // End-of-recording buffer discarded
uint32_t totalSamplesCaptured = 0;      // Total I2S samples read

uint32_t getWriterStallCount() { return writerStallCount; }
uint32_t getWriterStallMaxMs() { return writerStallMaxMs; }
uint32_t getFlushDropCount() { return flushDropCount; }
uint32_t getTotalSamplesCaptured() { return totalSamplesCaptured; }

uint32_t getRingFillLevel() {
    if (!audioRingBuf) return 0;
    UBaseType_t uxItemsWaiting = 0;
    vRingbufferGetInfo(audioRingBuf, NULL, NULL, NULL, NULL, &uxItemsWaiting);
    return (uint32_t)uxItemsWaiting;
}

// ── SD card mutex ─────────────────────────────────────────────────

void sdTake() {
    xSemaphoreTakeRecursive(sdMutex, portMAX_DELAY);
}

void sdGive() {
    xSemaphoreGiveRecursive(sdMutex);
}

// ── audioInit: mutex + I2S/AFE + writer + ring buffer ──────────────

void audioInit() {
    sdMutex = xSemaphoreCreateRecursiveMutex();

    // Initialize I2S microphone + AFE (VAD + NS + AGC)
    i2sFeInit();

    // Initialize writer (Opus encoder, upload queue, upload task)
    writerInit();

    // Allocate ring buffer in PSRAM via RTOS xRingbuffer (thread-safe, no mutex needed)
    uint8_t *ringStorage = (uint8_t *)ps_malloc(RING_TOTAL_BYTES);
    assert(ringStorage);
    StaticRingbuffer_t *ringStruct = (StaticRingbuffer_t *)ps_malloc(sizeof(StaticRingbuffer_t));
    assert(ringStruct);
    audioRingBuf = xRingbufferCreateStatic(RING_TOTAL_BYTES, RINGBUF_TYPE_NOSPLIT,
                                           ringStorage, ringStruct);
    assert(audioRingBuf);
    ESP_LOGI(TAG, "Ring buffer ready (RTOS NOSPLIT, %d items × %d bytes = %dms, %lu bytes)",
             RING_NUM_ITEMS, RING_ITEM_BYTES,
             (RING_NUM_ITEMS * RING_ITEM_BYTES * 1000) / (SAMPLE_RATE * 2),
             (unsigned long)RING_TOTAL_BYTES);
}

// ── Public API ─────────────────────────────────────────────────────

void startRecording(uint32_t durationMs) {
    if (recording) return;
    recordDurationMs = durationMs;
    recording = true;
}

void toggleVAD() {
    vadMode = !vadMode;
    ESP_LOGI(TAG, "Mode: %s", vadMode ? "VAD (auto)" : "Fixed duration");
}
