#pragma once
#include <Arduino.h>

// Writer — consumer + Opus + upload (writer.cpp)
void writerInit();
void writerTask(void *pvParameters);
uint32_t getUploadQueueDepth();
uint32_t getTotalSamplesWritten();
