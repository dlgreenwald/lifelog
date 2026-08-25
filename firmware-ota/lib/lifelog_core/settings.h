#pragma once
// Pure business logic for device settings.
// Zero Arduino dependencies.

#include <cstdint>
#include <cstring>

#define DEFAULT_HOSTNAME    "lifelog"
#define DEFAULT_SERVER_HOST "192.168.68.190"
#define DEFAULT_SERVER_PORT 8444
#define DEFAULT_SERVER_PATH "/api/v1/upload"
#define MAX_KNOWN_NETWORKS  5

struct KnownNetwork {
    char ssid[33];
    char password[65];
};

struct DeviceSettings {
    char hostname[32];
    char serverHost[64];
    uint16_t serverPort;
    char serverPath[64];
    char devicePassword[64];  // Protects ESPUI page + AP; empty = no auth
    // OAuth2 device code flow
    char oauthIssuer[128];
    char oauthClientId[128];
    char oauthScope[64];
};

// Add or update a known network. Deduplicates by SSID.
// Also used by native tests; main.cpp has its own static copy.
inline void addKnownNetwork(KnownNetwork *nets, int &count,
                            const char* ssid, const char* password) {
    for (int i = 0; i < count; i++) {
        if (strcmp(nets[i].ssid, ssid) == 0) {
            strlcpy(nets[i].password, password, 65);
            return;
        }
    }
    if (count < MAX_KNOWN_NETWORKS) {
        strlcpy(nets[count].ssid, ssid, 33);
        strlcpy(nets[count].password, password, 65);
        count++;
    }
}
