#pragma once
#include <Arduino.h>
#include "esp_log.h"

// Undo Arduino's ESP_LOG* hijacking — restore ESP-IDF runtime-filtered logging.
// Arduino redefines ESP_LOGI/W/E/D to log_i/w/e/d which bypass esp_log_level_set.
// These call esp_log_write directly, which respects esp_log_level_set per TAG.
// Format: [timestamp][I][file:line] function(): [TAG] message
#undef ESP_LOGE
#undef ESP_LOGW
#undef ESP_LOGI
#undef ESP_LOGD
#undef ESP_LOGV
#define _ESP_LOG_FMT(letter, format) \
    LOG_COLOR_##letter #letter " [%" PRIu32 "][%s:%d] %s(): [%s] " format LOG_RESET_COLOR "\n"
#define ESP_LOGE(tag, format, ...) esp_log_write(ESP_LOG_ERROR, tag, _ESP_LOG_FMT(E, format), esp_log_timestamp(), __FILE__, __LINE__, __FUNCTION__, tag, ##__VA_ARGS__)
#define ESP_LOGW(tag, format, ...) esp_log_write(ESP_LOG_WARN, tag, _ESP_LOG_FMT(W, format), esp_log_timestamp(), __FILE__, __LINE__, __FUNCTION__, tag, ##__VA_ARGS__)
#define ESP_LOGI(tag, format, ...) esp_log_write(ESP_LOG_INFO, tag, _ESP_LOG_FMT(I, format), esp_log_timestamp(), __FILE__, __LINE__, __FUNCTION__, tag, ##__VA_ARGS__)
#define ESP_LOGD(tag, format, ...) esp_log_write(ESP_LOG_DEBUG, tag, _ESP_LOG_FMT(D, format), esp_log_timestamp(), __FILE__, __LINE__, __FUNCTION__, tag, ##__VA_ARGS__)
#define ESP_LOGV(tag, format, ...) esp_log_write(ESP_LOG_VERBOSE, tag, _ESP_LOG_FMT(V, format), esp_log_timestamp(), __FILE__, __LINE__, __FUNCTION__, tag, ##__VA_ARGS__)

// LED — shares GPIO21 with SD CS on XIAO ESP32-S3 Sense.
// SD operations preempt LED via sdMutex (non-blocking take inside ledLoop()).
#define LED_PIN  21

// SD Card - XIAO ESP32-S3 Sense built-in slot
#define SD_CS_PIN   21

// PDM Microphone - Sense built-in
#define I2S_MIC_CLK  42
#define I2S_MIC_DIN  41

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
