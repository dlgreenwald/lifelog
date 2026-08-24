#pragma once
#include <Arduino.h>

// Audio settings
#define SAMPLE_RATE     16000

// Stall protection — max time A/B buffer swap waits for writer before dropping
#define VAD_STALL_TIMEOUT_MS  3000

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

// Upload queue depth
uint32_t getUploadQueueDepth();

// Functions
void audioInit();
void setWriterTaskHandle(TaskHandle_t handle);
void afeFeedTask(void *pvParameters);
void afeFetchTask(void *pvParameters);
void writerTask(void *pvParameters);
void startRecording(uint32_t durationMs);
void toggleVAD();

// Buffer health accessors
uint32_t getWriterStallCount();
uint32_t getWriterStallMaxMs();
uint32_t getDmaPartialCount();
uint32_t getFlushDropCount();
uint32_t getTotalSamplesCaptured();
uint32_t getTotalSamplesWritten();

