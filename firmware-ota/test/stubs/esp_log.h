#pragma once
// Minimal esp_log.h stub for native tests — enough for config.h's macro
// re-definition to parse and for led.cpp / other sources referencing it.

// esp-idf log levels (subset)
typedef int esp_log_level_t;
#define ESP_LOG_NONE     0
#define ESP_LOG_ERROR    1
#define ESP_LOG_WARN     2
#define ESP_LOG_INFO     3
#define ESP_LOG_DEBUG    4
#define ESP_LOG_VERBOSE  5

// Color codes used by config.h's format string
#define LOG_COLOR_E  ""
#define LOG_COLOR_W  ""
#define LOG_COLOR_I  ""
#define LOG_COLOR_D  ""
#define LOG_COLOR_V  ""
#define LOG_RESET_COLOR ""

// Function stubs
inline int esp_log_timestamp() { return 0; }
inline void esp_log_write(esp_log_level_t, const char*, const char*, ...) {}

// Arduino aliases config.h undef's then redefines
inline void log_i(const char*, ...) {}
inline void log_w(const char*, ...) {}
inline void log_e(const char*, ...) {}
inline void log_d(const char*, ...) {}
inline void log_v(const char*, ...) {}

#ifndef PRIu32
#define PRIu32 "u"
#endif
