#pragma once
#include <Arduino.h>
#include <RemoteDebug.h>

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

// Debug wrapper
extern RemoteDebug Debug;
#define LOG(fmt, ...) do { \
    Serial.printf(fmt "\n", ##__VA_ARGS__); \
    debugD(fmt, ##__VA_ARGS__); \
} while(0)
