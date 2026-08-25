// ESP32 OAuth2 client — Preferences-backed storage for the oauth2_device_flow library.

#include "oauth2_client.h"
#include <SD.h>
#include <Preferences.h>

static Preferences _oauthPrefs;
static const char* _oauthNS = "oauth2";
static OAuth2DeviceFlow _flow;

// ── Storage function pointers ──────────────────────────────────────

static void espPutString(const char* ns, const char* key, const char* value) {
    Preferences p;
    p.begin(ns, false);
    p.putString(key, value ? value : "");
    p.end();
}

static const char* espGetString(const char* ns, const char* key, const char* def) {
    Preferences p;
    p.begin(ns, true);
    String result = p.getString(key, def ? def : "");
    p.end();
    // Rotating static buffers — caller must copy before next getString call
    static char _bufs[4][512];
    static int idx = 0;
    char* buf = _bufs[idx++ & 3];
    strlcpy(buf, result.c_str(), 512);
    return buf;
}

static void espPutUint32(const char* ns, const char* key, uint32_t value) {
    Preferences p;
    p.begin(ns, false);
    p.putUInt(key, value);
    p.end();
}

static uint32_t espGetUint32(const char* ns, const char* key, uint32_t def) {
    Preferences p;
    p.begin(ns, true);
    uint32_t result = p.getUInt(key, def);
    p.end();
    return result;
}

static void espPutBool(const char* ns, const char* key, bool value) {
    Preferences p;
    p.begin(ns, false);
    p.putBool(key, value);
    p.end();
}

static bool espGetBool(const char* ns, const char* key, bool def) {
    Preferences p;
    p.begin(ns, true);
    bool result = p.getBool(key, def);
    p.end();
    return result;
}

static void espRemove(const char* ns, const char* key) {
    Preferences p;
    p.begin(ns, false);
    p.remove(key);
    p.end();
}

static void espClearNamespace(const char* ns) {
    Preferences p;
    p.begin(ns, false);
    p.clear();
    p.end();
}

static OAuth2Storage esp32Storage = {
    espPutString, espGetString,
    espPutUint32, espGetUint32,
    espPutBool, espGetBool,
    espRemove, espClearNamespace
};

// ── Public API ─────────────────────────────────────────────────────

void oauth2ClientInit() {
    _flow.begin(&esp32Storage);
}

OAuth2DeviceFlow& oauth2Client() {
    return _flow;
}
