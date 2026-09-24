#pragma once
#include <Arduino.h>
#include "lifelog_core/filename.h"

// Upload request — enqueued by writer, consumed by uploadTask
struct UploadRequest {
    char filename[64];
    uint8_t *mem_ptr;        // NULL if reading from SD
    uint32_t mem_size;
    uint32_t utteranceId;
    uint32_t chunkIndex;
    bool isFinal;
    bool from_sd;
    time_t recorded_at;      // UTC epoch seconds; 0 if clock invalid
    uint32_t start_ms;      // system uptime ms when voice start was detected
    uint32_t end_ms;        // system uptime ms when voice end was detected
};

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
void startUploadTask(TaskHandle_t *outHandle);
void setUploadQueueHandle(QueueHandle_t q);
QueueHandle_t getUploadQueueHandle();
// Upload OGG data directly from a memory buffer (no SD access, no sdMutex).
bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                          const char* filename, uint32_t utteranceId,
                          uint32_t chunkIndex, bool isFinal, time_t recordedAt,
                          uint32_t startMs, uint32_t endMs);
