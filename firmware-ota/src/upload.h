#pragma once
#include <Arduino.h>

// SD directory cache — PSRAM-resident, sorted alphanumerically
void sdDirCacheInit();
const char *sdDirCacheGetEntry(uint16_t i, time_t *outEpoch);
uint16_t sdDirCacheGetCount();
void sdDirCacheRemove(const char *filename);
void sdDirCacheInvalidate();
bool sdDirCacheAdd(const char *fullPath, time_t epoch);

// Functions
bool uploadFile(const char* filename, uint32_t utteranceId, uint32_t chunkIndex,
                bool isFinal, time_t recordedAt, uint32_t startMs, uint32_t endMs);
void uploadAllRecordings();
// Start background task that auto-uploads orphan SD recordings every 30s
void startAutoUploadTask();
void startUploadMonitorTask();
// Upload OGG data directly from a memory buffer (no SD access, no sdMutex).
bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                          const char* filename, uint32_t utteranceId,
                          uint32_t chunkIndex, bool isFinal, time_t recordedAt,
                          uint32_t startMs, uint32_t endMs);
