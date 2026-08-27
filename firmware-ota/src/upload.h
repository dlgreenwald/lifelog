#pragma once
#include <Arduino.h>

// Functions
bool uploadFile(const char* filename, uint32_t utteranceId, uint32_t chunkIndex, bool isFinal);
void uploadAllRecordings();
// Upload OGG data directly from a memory buffer (no SD access, no sdMutex).
bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                          const char *filename, uint32_t utteranceId,
                          uint32_t chunkIndex, bool isFinal);
