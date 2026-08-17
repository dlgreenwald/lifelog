#pragma once
#include <Arduino.h>

// LED
#define LED_PIN  21

// SD Card - XIAO ESP32-S3 Sense built-in slot
#define SD_CS_PIN   21

// PDM Microphone - Sense built-in
#define I2S_MIC_CLK  42
#define I2S_MIC_DIN  41

// Server
#define SERVER_HOST    "192.168.68.190"
#define SERVER_PORT    8443
#define SERVER_PATH    "/api/v1/upload"
#define API_KEY        "lifelog-key"

// ── Compile-time log levels ────────────────────────────────────────
#define LOG_NONE  0
#define LOG_ERROR 1
#define LOG_WARN  2
#define LOG_INFO  3
#define LOG_DEBUG 4

// ── Per-component log levels ───────────────────────────────────────
// Change these to filter output per component at build time
#define LOG_BOOT_LEVEL    LOG_INFO
#define LOG_WIFI_LEVEL    LOG_INFO
#define LOG_OTA_LEVEL     LOG_INFO
#define LOG_SYSTEM_LEVEL  LOG_INFO
#define LOG_SD_LEVEL      LOG_DEBUG
#define LOG_I2S_LEVEL     LOG_INFO
#define LOG_AUDIO_LEVEL   LOG_INFO
#define LOG_VAD_LEVEL     LOG_DEBUG
#define LOG_UPLOAD_LEVEL  LOG_WARN
#define LOG_CMD_LEVEL     LOG_DEBUG
#define LOG_MIC_LEVEL     LOG_DEBUG
#define LOG_LS_LEVEL      LOG_DEBUG

// ── Component macros ───────────────────────────────────────────────
// Usage: LOG_SD(LOG_INFO, "Mounted: %s", name);
//        LOG_VAD(LOG_DEBUG, "RMS=%.0f", rms);
//        LOG_UPLOAD(LOG_ERROR, "Failed: %s", err);

#define LOG_BOOT(lvl, fmt, ...) \
    do { if (LOG_BOOT_LEVEL >= (lvl)) Serial.printf("[BOOT] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_WIFI(lvl, fmt, ...) \
    do { if (LOG_WIFI_LEVEL >= (lvl)) Serial.printf("[WIFI] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_OTA(lvl, fmt, ...) \
    do { if (LOG_OTA_LEVEL >= (lvl)) Serial.printf("[OTA] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_SYSTEM(lvl, fmt, ...) \
    do { if (LOG_SYSTEM_LEVEL >= (lvl)) Serial.printf("[SYSTEM] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_SD(lvl, fmt, ...) \
    do { if (LOG_SD_LEVEL >= (lvl)) Serial.printf("[SD] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_I2S(lvl, fmt, ...) \
    do { if (LOG_I2S_LEVEL >= (lvl)) Serial.printf("[I2S] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_AUDIO(lvl, fmt, ...) \
    do { if (LOG_AUDIO_LEVEL >= (lvl)) Serial.printf("[AUDIO] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_VAD(lvl, fmt, ...) \
    do { if (LOG_VAD_LEVEL >= (lvl)) Serial.printf("[VAD] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_UPLOAD(lvl, fmt, ...) \
    do { if (LOG_UPLOAD_LEVEL >= (lvl)) Serial.printf("[UPLOAD] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_CMD(lvl, fmt, ...) \
    do { if (LOG_CMD_LEVEL >= (lvl)) Serial.printf("[CMD] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_MIC(lvl, fmt, ...) \
    do { if (LOG_MIC_LEVEL >= (lvl)) Serial.printf("[MIC] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_LS(lvl, fmt, ...) \
    do { if (LOG_LS_LEVEL >= (lvl)) Serial.printf("[LS] " fmt "\n", ##__VA_ARGS__); } while(0)
