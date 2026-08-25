#pragma once
#include <Arduino.h>

// LED
#define LED_PIN  21

// SD Card - XIAO ESP32-S3 Sense built-in slot
#define SD_CS_PIN   21

// PDM Microphone - Sense built-in
#define I2S_MIC_CLK  42
#define I2S_MIC_DIN  41

// Server — API_KEY kept as fallback for deviceSettings.apiKey
#define API_KEY        "07a12a33ae0f36b02e1a54ff158402efafeac9832b013592bd8e5f5061c7eb31"

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
#define LOG_SYSTEM_LEVEL  LOG_WARN
#define LOG_SD_LEVEL      LOG_DEBUG
#define LOG_I2S_LEVEL     LOG_INFO
#define LOG_AUDIO_LEVEL   LOG_INFO
#define LOG_VAD_LEVEL     LOG_INFO
#define LOG_AFE_LEVEL     LOG_INFO
#define LOG_UPLOAD_LEVEL  LOG_INFO
#define LOG_CMD_LEVEL     LOG_DEBUG
#define LOG_MIC_LEVEL     LOG_DEBUG
#define LOG_LS_LEVEL     LOG_DEBUG
#define LOG_OAUTH_LEVEL  LOG_INFO

// ── Audio format selection (set via build_flags: -DAUDIO_FORMAT_OPUS) ──
#if defined(AUDIO_FORMAT_OPUS)
  #define AUDIO_FORMAT_OPUS_ACTIVE 1
#else
  #define AUDIO_FORMAT_WAV_ACTIVE 1
#endif

// Opus encoder settings (used when AUDIO_FORMAT_OPUS_ACTIVE)
#define AUDIO_OPUS_FRAME_MS   20    // Opus frame size: 20ms (320 samples at 16kHz)
#define AUDIO_OPUS_BITRATE    24000 // 24 kbps — good quality for speech at 16kHz
#define AUDIO_OPUS_COMPLEXITY 5     // 0-10, balance CPU vs quality

// ── Component macros ───────────────────────────────────────────────
// Usage: LOG_SD(LOG_INFO, "Mounted: %s", name);
//        LOG_VAD(LOG_DEBUG, "RMS=%.0f", rms);
//        LOG_UPLOAD(LOG_ERROR, "Failed: %s", err);

#define LOG_TS Serial.printf("[%lu] ", millis())

#define LOG_BOOT(lvl, fmt, ...) \
    do { if (LOG_BOOT_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[BOOT] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_WIFI(lvl, fmt, ...) \
    do { if (LOG_WIFI_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[WIFI] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_OTA(lvl, fmt, ...) \
    do { if (LOG_OTA_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[OTA] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_SYSTEM(lvl, fmt, ...) \
    do { if (LOG_SYSTEM_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[SYSTEM] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_SD(lvl, fmt, ...) \
    do { if (LOG_SD_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[SD] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_I2S(lvl, fmt, ...) \
    do { if (LOG_I2S_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[I2S] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_AUDIO(lvl, fmt, ...) \
    do { if (LOG_AUDIO_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[AUDIO] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_VAD(lvl, fmt, ...) \
    do { if (LOG_VAD_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[VAD] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_AFE(lvl, fmt, ...) \
    do { if (LOG_AFE_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[AFE] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_UPLOAD(lvl, fmt, ...) \
    do { if (LOG_UPLOAD_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[UPLOAD] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_CMD(lvl, fmt, ...) \
    do { if (LOG_CMD_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[CMD] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_MIC(lvl, fmt, ...) \
    do { if (LOG_MIC_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[MIC] " fmt "\n", ##__VA_ARGS__); } } while(0)
#define LOG_LS(lvl, fmt, ...) \
    do { if (LOG_LS_LEVEL >= (lvl)) Serial.printf("[LS] " fmt "\n", ##__VA_ARGS__); } while(0)
#define LOG_OAUTH(lvl, fmt, ...) \
    do { if (LOG_OAUTH_LEVEL >= (lvl)) { LOG_TS; Serial.printf("[OAUTH] " fmt "\n", ##__VA_ARGS__); } } while(0)
