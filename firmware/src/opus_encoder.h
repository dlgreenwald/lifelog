#pragma once
#include <Arduino.h>
#include "audio_capture.h"

typedef struct {
    uint8_t data[1024];
    size_t length;
} OpusFrame;

void opusEncodeTask(void *pvParameters);
