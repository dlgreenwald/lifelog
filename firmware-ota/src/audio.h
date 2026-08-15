#pragma once
#include <Arduino.h>
#include <driver/i2s.h>
#include <SD.h>

// Audio settings
#define SAMPLE_RATE     16000
#define OPUS_BITRATE    24000
#define OPUS_FRAME_SIZE 960   // 60ms at 16kHz
#define CHUNK_SAMPLES   (SAMPLE_RATE * 5)  // 5 seconds per chunk

// VAD settings
#define VAD_THRESHOLD   20    // Very low - always recording for testing
#define VAD_SILENCE_MS  1500  // 1.5s silence = end of utterance
#define VAD_CHUNK_MS    30    // 30ms I2S read chunks
#define VAD_ANALYSIS_MS 200   // 200ms analysis window for RMS
#define VAD_BG_ADAPT    1.5   // Speech threshold = background * 1.5
#define VAD_BG_SAMPLES  50    // Background noise samples to average

// Queue settings
#define AUDIO_QUEUE_SIZE  10  // Max chunks in queue
#define CHUNK_QUEUE_BYTES (CHUNK_SAMPLES * 2 + sizeof(int) + 16)  // PCM + metadata

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
