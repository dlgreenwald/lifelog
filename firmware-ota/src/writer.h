#pragma once
#include <Arduino.h>

// Writer — consumer + Opus + upload (writer.cpp)
void writerInit();
void writerTask(void *pvParameters);
uint32_t getUploadQueueDepth();
uint32_t getTotalSamplesWritten();
TaskHandle_t getUploadTaskHandle();
// PSRAM memory buffer stats (dashboard)
uint32_t getMemBufUsed();
uint32_t getMemBufCapacity();
bool isMemToSd();
