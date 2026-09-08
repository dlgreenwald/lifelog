#pragma once
#include <Arduino.h>

bool uploadFile(const char* filename, uint32_t utteranceId, uint32_t chunkIndex,
                bool isFinal, time_t recordedAt);
void uploadAllRecordings();
void startAutoUploadTask();
// Upload OGG data directly from a memory buffer (no SD access, no sdMutex).
bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                          const char *filename, uint32_t utteranceId,
                          uint32_t chunkIndex, bool isFinal,
                          time_t recordedAt);
