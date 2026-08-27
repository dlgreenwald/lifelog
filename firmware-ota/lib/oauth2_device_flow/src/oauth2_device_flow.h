#pragma once
// OAuth2 RFC 8628 Device Code Flow — public API
// Wraps esp_http_client with transparent auth injection and token lifecycle.
// Caller owns the esp_http_client handle — full control over TLS, URL, streaming.

#include <cstdint>
#include <ArduinoJson.h>
#if !defined(OAUTH2_TESTING)
#include "esp_log.h"
#endif

// ── Platform type stubs (for native tests) ────────────────────────
#if !defined(ARDUINO) || defined(OAUTH2_TESTING)
typedef void* TaskHandle_t;
typedef void* SemaphoreHandle_t;
#endif

// ── Platform storage abstraction ───────────────────────────────────

struct OAuth2Storage {
    void (*putString)(const char* ns, const char* key, const char* value);
    const char* (*getString)(const char* ns, const char* key, const char* defaultVal);
    void (*putUint32)(const char* ns, const char* key, uint32_t value);
    uint32_t (*getUint32)(const char* ns, const char* key, uint32_t defaultVal);
    void (*putBool)(const char* ns, const char* key, bool value);
    bool (*getBool)(const char* ns, const char* key, bool defaultVal);
    void (*remove)(const char* ns, const char* key);
    void (*clearNamespace)(const char* ns);
};

// ── Auth state ─────────────────────────────────────────────────────

enum AuthState : uint8_t {
    AUTH_IDLE = 0,
    AUTH_REQUESTING_CODE = 1,
    AUTH_DISPLAYING_CODE = 2,
    AUTH_POLLING = 3,
    AUTHENTICATED = 4,
    AUTH_ERROR = 5
};

// ── Configuration ──────────────────────────────────────────────────

struct OAuth2Config {
    const char* issuer;      // Auth server URL (token endpoints only)
    const char* clientId;    // Public client ID
    const char* scope;       // e.g. "openid offline_access"
    uint32_t timeoutMs = 600000;
};

// ── HTTP response (for one-shot convenience methods) ───────────────

struct OAuth2HttpResponse {
    int statusCode;
    JsonDocument body;
};

// ── Library class ──────────────────────────────────────────────────

class OAuth2DeviceFlow {
public:
    // ── Setup (call once) ───────────────────────────────────────────
    void begin(OAuth2Storage* storage);
    void configure(const OAuth2Config& config);

    // ── Device code registration flow ───────────────────────────────
    void start();   // Boot: create polling task, resume if already in progress
    void stop();
    void requestAuth();  // User action: explicitly start device code flow

    // ── State queries ───────────────────────────────────────────────
    AuthState getState() const;
    const char* getUserCode() const;
    const char* getVerificationUri() const;
    const char* getVerificationUriComplete() const;
    bool hasValidToken() const;
    uint32_t getTokenExpiresInSeconds() const;
    uint32_t getRefreshTokenExpiresInSeconds() const;
    const char* getLastError() const;

    // ── Token management ────────────────────────────────────────────
    void refreshToken();
    void clearTokens();
    void clearConfig();
    void loadSavedState();
    bool ensureValidToken();  // Refresh if expired; returns true if token available

    // ── esp_http_client proxy ───────────────────────────────────────
    // Wrap an existing esp_http_client handle. Auth injected transparently.
    // Same lifecycle as esp_http_client — caller controls everything.
    //
    // 401 RETRY: On 401, the proxy refreshes the token and returns -401
    // from get_status_code(). The caller MUST retry the entire request
    // (close, re-open, re-write body). The proxy does NOT buffer the
    // request body — for multipart uploads, re-stream the file on retry.
    void setTransport(void* client);

    // Open connection — injects Authorization: Bearer header
    int open(int write_len);

    // Write request body — streams data through underlying client
    int write(const void* data, int len);

    // Fetch response headers — if 401, refreshes token, closes, returns -401
    int fetch_headers();

    // Get response status code — returns -401 if retry needed
    int get_status_code();

    // Read response body
    int read(void* buf, int len);

    // Close connection
    void close();

    // ── One-shot convenience (creates esp_http_client internally) ───
    OAuth2HttpResponse get(const char* path);
    OAuth2HttpResponse post(const char* path, const char* body);
    OAuth2HttpResponse put(const char* path, const char* body);
    OAuth2HttpResponse patch(const char* path, const char* body);
    OAuth2HttpResponse del(const char* path);

    // ── Test hooks ──────────────────────────────────────────────────
#ifdef OAUTH2_TESTING
    void _testSetHttpResponse(int status, const char* jsonBody);
    void pollOnce();
#endif

private:
    // Internal HTTP (for auth server requests and one-shot methods)
    OAuth2HttpResponse requestInternal(const char* method, const char* url,
                                       const char* extraHeaders, const char* body);
    OAuth2HttpResponse doWithRetry(const char* method, const char* path,
                                   const char* body);

    // Device code flow internals
    void requestDeviceCode();
    void pollToken();
    void exchangeRefreshToken();
    void saveTokens();
    void loadTokens();
    void saveDeviceCodeInfo();
    void loadDeviceCodeInfo();
    void setState(AuthState s);

    // Background task
    static void pollingTaskEntry(void* param);
    void pollingTaskLoop();
    static uint32_t nowMs();

    OAuth2Storage* _storage = nullptr;
    OAuth2Config _config = {};
    // Persistent buffers for config strings — _config pointers reference these
    char _cfgIssuer[128] = {};
    char _cfgClientId[128] = {};
    char _cfgScope[64] = {};

    AuthState _state = AUTH_IDLE;
    char _deviceCode[256] = {};
    char _userCode[32] = {};
    char _verificationUri[256] = {};
    char _verificationUriComplete[512] = {};
    char _accessToken[2048] = {};
    char _refreshToken[512] = {};
    char _lastError[128] = {};
    uint32_t _tokenExpiry = 0;
    uint32_t _refreshTokenExpiry = 0;  // Epoch seconds; 0 = no expiry known
    uint16_t _pollInterval = 5000;
    uint32_t _lastPollTime = 0;
    uint32_t _flowStartTime = 0;
    uint32_t _deviceCodeExpiry = 0;  // Epoch millis when device code expires
    bool _hasTokens = false;

    void* _pollingTaskHandle = nullptr;
    void* _mutex = nullptr;

    // Proxy state
    void* _transport = nullptr;
    int _pendingStatus = 0;  // -401 = retry needed after token refresh

#ifdef OAUTH2_TESTING
    int _mockHttpStatus = 0;
    char _mockHttpBody[4096] = {};
    bool _mockHttpReady = false;
#endif
};
