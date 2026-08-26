#pragma once
#include <Arduino.h>
#include "freertos/ringbuf.h"

// Audio settings
#define SAMPLE_RATE     16000

// Ring buffer — producer writes, consumer reads
extern RingbufHandle_t audioRingBuf;
#define RING_ITEM_BYTES  1024   // 512 samples × 2 bytes — one AFE chunk
#define RING_NUM_ITEMS   32     // 32 × 32ms = 1024ms buffered
#define RING_TOTAL_BYTES ((size_t)(RING_ITEM_BYTES + 16) * RING_NUM_ITEMS)

// Public state
extern volatile bool recording;
extern volatile bool vadMode;
// SD card mutex — guards all SD SPI access
extern SemaphoreHandle_t sdMutex;
void sdTake();
void sdGive();
extern uint32_t fileIndex;
extern char lastSavedFile[64];

// Utterance tracking
extern volatile uint32_t utteranceId;   // Monotonic counter, incremented on voice start
extern volatile uint32_t chunkIndex;    // Reset to 0 on voice start, incremented per buffer
extern volatile bool isFinal;           // Set true when silence ends utterance

// Shared pipeline state (accessed by i2s_fe.cpp, writer.cpp)
extern TaskHandle_t writerTaskHandle;

// Buffer health (counters shared with i2s_fe.cpp)
extern uint32_t flushDropCount;
extern uint32_t totalSamplesCaptured;

// Buffer health accessors
uint32_t getWriterStallCount();
uint32_t getWriterStallMaxMs();
uint32_t getFlushDropCount();
uint32_t getTotalSamplesCaptured();
uint32_t getRingFillLevel();

// Functions
void audioInit();
void startRecording(uint32_t durationMs);
void toggleVAD();
