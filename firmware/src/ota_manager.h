#pragma once
#include <Arduino.h>

// OTA HTTP server port
#define OTA_SERVER_PORT 8080

// Boot confirmation settings
#define OTA_MAX_BOOT_ATTEMPTS 3  // Max boots without confirmation before rollback
#define OTA_CONFIRM_TIMEOUT_MS 30000  // 30s to confirm after boot

// Initialize OTA manager (call early in setup)
void otaManagerInit();

// Start the OTA HTTP server
void otaServerStart();

// Mark current firmware as confirmed (call after successful init)
void otaConfirmFirmware();

// Get current OTA slot info
int otaGetCurrentSlot();
int otaGetBootAttempts();

// Handle OTA server requests (call in loop)
void otaServerHandleClient();
