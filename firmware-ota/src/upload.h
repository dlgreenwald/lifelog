#pragma once
#include <Arduino.h>

// Functions
bool uploadFile(const char* filename, uint32_t utteranceId, uint32_t chunkIndex, bool isFinal);
void uploadAllRecordings();
