#pragma once

// INMP441 Microphone Pins (I2S)
#define I2S_MIC_WS    42   // Word Select
#define I2S_MIC_SCK   41   // Serial Clock
#define I2S_MIC_SD    43   // Serial Data

// SD Card (SPI)
#define SD_CS_PIN     2
#define SD_MOSI       38
#define SD_MISO       39
#define SD_SCLK       40

// Battery ADC
#define BATTERY_ADC_PIN  3  // A0 pin (check XIAO pinout)

// Status LED
#define LED_BLUE_PIN    21  // Built-in blue LED

// Thresholds
#define BATTERY_LOW_VOLTAGE    3.3   // ~10% remaining
#define BATTERY_CRITICAL_VOLTAGE 3.0 // Stop recording
#define VAD_THRESHOLD          500   // RMS amplitude threshold

// Server (HTTPS)
#define SERVER_HOST    "your-server.local"
#define SERVER_PORT    443
#define SERVER_PATH    "/api/v1/upload"

// API Key - configure per device (32-64 character string)
// This identifies the device/user to the server
#define API_KEY        "your-api-key-here"

// WiFi credentials
#define WIFI_SSID      "your-wifi-ssid"
#define WIFI_PASSWORD  "your-wifi-password"

// Audio settings
#define SAMPLE_RATE    16000
#define OPUS_BITRATE   24000
#define PCM_BUFFER_SIZE 480  // 30ms at 16kHz
#define OPUS_FRAME_SIZE 960  // 60ms at 16kHz
