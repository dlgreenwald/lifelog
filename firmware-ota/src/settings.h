#pragma once
#include <Arduino.h>

#define DEFAULT_HOSTNAME    "lifelog"
#define DEFAULT_SERVER_HOST "192.168.68.190"
#define DEFAULT_SERVER_PORT 8444
#define DEFAULT_SERVER_PATH "/api/v1/upload"
#define MAX_KNOWN_NETWORKS  5
#define WIFI_CONNECT_TIMEOUT_MS 10000

struct KnownNetwork {
    char ssid[33];
    char password[65];
};

struct DeviceSettings {
    char hostname[32];
    char serverHost[64];
    uint16_t serverPort;
    char serverPath[64];
    char apiKey[128];
    char devicePassword[64];  // Protects ESPUI page + AP; empty = no auth
};

extern DeviceSettings deviceSettings;
extern KnownNetwork knownNetworks[MAX_KNOWN_NETWORKS];
extern int knownNetworkCount;
