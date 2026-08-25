#pragma once
// ESP32 OAuth2 client — wires the oauth2_device_flow library to NVS via Preferences.
// Thin wrapper: creates a static OAuth2DeviceFlow instance with ESP32 storage.

#include <oauth2_device_flow.h>

// Initialize the OAuth2 client with ESP32 NVS storage. Call once in setup().
void oauth2ClientInit();

// Get the configured instance. Use after oauth2ClientInit().
OAuth2DeviceFlow& oauth2Client();
