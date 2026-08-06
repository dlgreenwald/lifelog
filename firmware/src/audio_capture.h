#pragma once
#include <Arduino.h>
#include "config.h"

typedef struct {
    int16_t data[PCM_BUFFER_SIZE];
    size_t length;  // 0 = end-of-utterance marker
} AudioChunk;

void audioCaptureTask(void *pvParameters);
float computeRMS(int16_t *samples, int count);
