#pragma once
#include <Arduino.h>

// Audio settings
#define SAMPLE_RATE     16000

// VAD settings
#define VAD_THRESHOLD   700
#define VAD_SILENCE_MS  1500
#define VAD_CHUNK_MS    30
#define VAD_ANALYSIS_MS 200
#define VAD_GAIN        3

// Public state
extern volatile bool recording;
extern volatile bool vadMode;
extern uint32_t fileIndex;
extern char lastSavedFile[64];

// Functions
void audioInit();
void audioTask(void *pvParameters);
void writerTask(void *pvParameters);
void startRecording(uint32_t durationMs);
void toggleVAD();
