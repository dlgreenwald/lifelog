// OAuth2 RFC 8628 Device Code Flow — implementation
// Wraps esp_http_client with transparent auth injection and token lifecycle.

#include "oauth2_device_flow.h"
#include <cstring>
#include <ctime>

// ── Platform HTTP (esp_http_client or test mock) ───────────────────

#ifdef OAUTH2_TESTING
static bool mockHttpResponseReady = false;
static int mockHttpStatus = 0;
static char mockHttpBody[4096] = {};

void OAuth2DeviceFlow::_testSetHttpResponse(int status, const char* jsonBody) {
    mockHttpStatus = status;
    if (jsonBody) strlcpy(mockHttpBody, jsonBody, sizeof(mockHttpBody));
    else mockHttpBody[0] = '\0';
    mockHttpResponseReady = true;
}

void OAuth2DeviceFlow::pollOnce() {
    if (_state == AUTH_POLLING) {
        if (nowMs() - _flowStartTime > _config.timeoutMs) {
            strlcpy(_lastError, "Timed out", sizeof(_lastError));
            setState(AUTH_ERROR);
            return;
        }
        pollToken();
    } else if (_state == AUTH_DISPLAYING_CODE) {
        setState(AUTH_POLLING);
    }
}
#else
#include <esp_http_client.h>
// ESP-IDF cert bundle — the symbol is in precompiled libmbedtls.a
extern "C" esp_err_t esp_crt_bundle_attach(void *conf);
#endif

static const char* NS = "oauth2";

// Forward declaration
static uint32_t parseJwtExp(const char* jwt);

// ── Portable time source ───────────────────────────────────────────

uint32_t OAuth2DeviceFlow::nowMs() {
#ifdef OAUTH2_TESTING
    extern uint32_t _oauth2_test_mock_time;
    return _oauth2_test_mock_time;
#else
    return millis();
#endif
}

// ── Lifecycle ──────────────────────────────────────────────────────

void OAuth2DeviceFlow::begin(OAuth2Storage* storage) {
    _storage = storage;
    loadSavedState();
}

void OAuth2DeviceFlow::configure(const OAuth2Config& config) {
    // Copy into class-owned buffers — caller's pointers may be stack-local
    strlcpy(_cfgIssuer, config.issuer ? config.issuer : "", sizeof(_cfgIssuer));
    strlcpy(_cfgClientId, config.clientId ? config.clientId : "", sizeof(_cfgClientId));
    strlcpy(_cfgScope, config.scope ? config.scope : "", sizeof(_cfgScope));
    _config.issuer = _cfgIssuer;
    _config.clientId = _cfgClientId;
    _config.scope = _cfgScope;
    _config.timeoutMs = config.timeoutMs;

    if (_storage) {
        _storage->putString(NS, "issuer", _cfgIssuer);
        _storage->putString(NS, "client_id", _cfgClientId);
        _storage->putString(NS, "scope", _cfgScope);
        _storage->putUint32(NS, "timeout_ms", _config.timeoutMs);
    }
}

// ── State management ───────────────────────────────────────────────

// Read-only getters: safe without mutex on ESP32 (Xtensa).
// Single-writer (polling task) publishes these; main thread reads.
// Aligned 32-bit and pointer reads are atomic on Xtensa.
AuthState OAuth2DeviceFlow::getState() const { return _state; }
const char* OAuth2DeviceFlow::getUserCode() const { return _userCode; }
const char* OAuth2DeviceFlow::getVerificationUri() const { return _verificationUri; }
const char* OAuth2DeviceFlow::getVerificationUriComplete() const { return _verificationUriComplete; }
const char* OAuth2DeviceFlow::getLastError() const { return _lastError; }

bool OAuth2DeviceFlow::hasValidToken() const {
    if (!_hasTokens || _accessToken[0] == '\0') return false;
    return static_cast<uint32_t>(time(NULL)) < _tokenExpiry;
}

uint32_t OAuth2DeviceFlow::getTokenExpiresInSeconds() const {
    if (!_hasTokens || static_cast<uint32_t>(time(NULL)) >= _tokenExpiry) return 0;
    return _tokenExpiry - static_cast<uint32_t>(time(NULL));
}

uint32_t OAuth2DeviceFlow::getRefreshTokenExpiresInSeconds() const {
    if (!_hasTokens || _refreshToken[0] == '\0' || _refreshTokenExpiry == 0) return 0;
    uint32_t nowSec = static_cast<uint32_t>(time(NULL));
    if (nowSec >= _refreshTokenExpiry) return 0;
    return _refreshTokenExpiry - nowSec;
}

void OAuth2DeviceFlow::setState(AuthState s) {
    _state = s;
    if (_storage) _storage->putUint32(NS, "state", static_cast<uint32_t>(s));
}

// ── Start / Stop ───────────────────────────────────────────────────

void OAuth2DeviceFlow::start() {
    if (!_mutex) {
#ifdef OAUTH2_TESTING
        _mutex = reinterpret_cast<void*>(static_cast<intptr_t>(1));
#else
        _mutex = xSemaphoreCreateMutex();
#endif
    }
#ifndef OAUTH2_TESTING
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
    if (_state == AUTH_POLLING || _state == AUTH_DISPLAYING_CODE || _state == AUTHENTICATED) {
        // If authenticated but token expired and no refresh token, restart device code flow
        if (_state == AUTHENTICATED && (!_hasTokens || _refreshToken[0] == '\0' ||
            static_cast<uint32_t>(time(NULL)) >= _tokenExpiry)) {
#ifndef OAUTH2_TESTING
            OAUTH_LOG(1, "Token expired/unavailable on startup, restarting device code flow");
#endif
            // Clear stale tokens directly (can't call clearTokens() — mutex already held)
            _accessToken[0] = '\0';
            _refreshToken[0] = '\0';
            _tokenExpiry = 0;
            _refreshTokenExpiry = 0;
            _hasTokens = false;
            if (_storage) {
                _storage->remove(NS, "access_token");
                _storage->remove(NS, "refresh_token");
                _storage->remove(NS, "token_expiry");
                _storage->remove(NS, "refresh_exp");
                _storage->putBool(NS, "has_tokens", false);
            }
            if (_config.issuer && _config.issuer[0]) {
                setState(AUTH_REQUESTING_CODE);
                _flowStartTime = nowMs();
            } else {
                setState(AUTH_IDLE);
            }
        }
        if (_pollingTaskHandle) {
#ifndef OAUTH2_TESTING
            xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
            vTaskResume(static_cast<TaskHandle_t>(_pollingTaskHandle));
            OAUTH_LOG(1, "Resumed polling task (state=%d)", _state);
#endif
        } else {
            // State restored from NVS but task was never created (e.g. boot with valid token)
#ifndef OAUTH2_TESTING
            int savedState = _state;
            xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
            xTaskCreatePinnedToCore(pollingTaskEntry, "oauth2_poll", 8192,
                                    this, 2, reinterpret_cast<TaskHandle_t*>(&_pollingTaskHandle), 1);
            OAUTH_LOG(1, "Created polling task (state=%d)", savedState);
#endif
        }
        return;
    }
    setState(AUTH_REQUESTING_CODE);
    _lastError[0] = '\0';
    _flowStartTime = nowMs();
#ifndef OAUTH2_TESTING
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
#endif
    if (_pollingTaskHandle) {
#ifndef OAUTH2_TESTING
        vTaskResume(static_cast<TaskHandle_t>(_pollingTaskHandle));
#endif
    } else {
#ifndef OAUTH2_TESTING
        xTaskCreatePinnedToCore(pollingTaskEntry, "oauth2_poll", 8192,
                                this, 2, reinterpret_cast<TaskHandle_t*>(&_pollingTaskHandle), 1);
#else
        pollingTaskLoop();
#endif
    }
}

void OAuth2DeviceFlow::stop() {
#ifndef OAUTH2_TESTING
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
    setState(AUTH_IDLE);
#ifndef OAUTH2_TESTING
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
#endif
    if (_pollingTaskHandle) {
#ifndef OAUTH2_TESTING
        vTaskSuspend(static_cast<TaskHandle_t>(_pollingTaskHandle));
#endif
    }
}

// ── Storage persistence ────────────────────────────────────────────

void OAuth2DeviceFlow::saveTokens() {
    if (!_storage) return;
    _storage->putString(NS, "access_token", _accessToken);
    _storage->putString(NS, "refresh_token", _refreshToken);
    _storage->putUint32(NS, "token_expiry", _tokenExpiry);
    _storage->putUint32(NS, "refresh_exp", _refreshTokenExpiry);
    _storage->putBool(NS, "has_tokens", _hasTokens);
}

void OAuth2DeviceFlow::loadTokens() {
    if (!_storage) return;
    strlcpy(_accessToken, _storage->getString(NS, "access_token", ""), sizeof(_accessToken));
    strlcpy(_refreshToken, _storage->getString(NS, "refresh_token", ""), sizeof(_refreshToken));
    _tokenExpiry = _storage->getUint32(NS, "token_expiry", 0);
    _refreshTokenExpiry = _storage->getUint32(NS, "refresh_exp", 0);
    _hasTokens = _storage->getBool(NS, "has_tokens", false);
}

void OAuth2DeviceFlow::saveDeviceCodeInfo() {
    if (!_storage) return;
    _storage->putString(NS, "device_code", _deviceCode);
    _storage->putString(NS, "user_code", _userCode);
    _storage->putString(NS, "ver_uri", _verificationUri);
    _storage->putString(NS, "ver_uri_full", _verificationUriComplete);
    _storage->putUint32(NS, "poll_int", _pollInterval);
}

void OAuth2DeviceFlow::loadDeviceCodeInfo() {
    if (!_storage) return;
    strlcpy(_deviceCode, _storage->getString(NS, "device_code", ""), sizeof(_deviceCode));
    strlcpy(_userCode, _storage->getString(NS, "user_code", ""), sizeof(_userCode));
    strlcpy(_verificationUri, _storage->getString(NS, "ver_uri", ""), sizeof(_verificationUri));
    strlcpy(_verificationUriComplete, _storage->getString(NS, "ver_uri_full", ""), sizeof(_verificationUriComplete));
    _pollInterval = static_cast<uint16_t>(_storage->getUint32(NS, "poll_int", 5000));
}

void OAuth2DeviceFlow::loadSavedState() {
    if (!_storage) return;
    loadTokens();
    loadDeviceCodeInfo();

    // Copy each value into class-owned buffers — getString rotates shared static buffers
    strlcpy(_cfgIssuer, _storage->getString(NS, "issuer", ""), sizeof(_cfgIssuer));
    strlcpy(_cfgClientId, _storage->getString(NS, "client_id", ""), sizeof(_cfgClientId));
    strlcpy(_cfgScope, _storage->getString(NS, "scope", "openid offline_access"), sizeof(_cfgScope));
    _config.issuer = _cfgIssuer;
    _config.clientId = _cfgClientId;
    _config.scope = _cfgScope;
    _config.timeoutMs = _storage->getUint32(NS, "timeout_ms", 600000);
    _state = static_cast<AuthState>(_storage->getUint32(NS, "state", static_cast<uint32_t>(AUTH_IDLE)));

    // Parse JWT exp to get accurate token expiry
    if (_hasTokens && _accessToken[0] != '\0') {
        uint32_t jwtExp = parseJwtExp(_accessToken);
        if (jwtExp > 0) _tokenExpiry = jwtExp;
    }

    // Validate token state on boot — don't trust NVS blindly
    if (_state == AUTHENTICATED && _hasTokens && _accessToken[0] != '\0') {
        uint32_t nowSec = static_cast<uint32_t>(time(NULL));
        if (_tokenExpiry > 0 && nowSec >= _tokenExpiry) {
            // Access token expired — can we recover?
            if (_refreshToken[0] != '\0') {
                // Have refresh token → stay AUTHENTICATED, background task will refresh
#ifndef OAUTH2_TESTING
                OAUTH_LOG(1, "Boot: access token expired, refresh token available");
#endif
            } else {
                // No refresh token → must re-authenticate from scratch
#ifndef OAUTH2_TESTING
                OAUTH_LOG(1, "Boot: access token expired, no refresh token — restarting auth");
#endif
                _accessToken[0] = '\0';
                _tokenExpiry = 0;
                _refreshTokenExpiry = 0;
                _hasTokens = false;
                _storage->remove(NS, "access_token");
                _storage->remove(NS, "token_expiry");
                _storage->remove(NS, "refresh_exp");
                _storage->putBool(NS, "has_tokens", false);
                // Set state so start() goes straight to device code flow
                if (_config.issuer && _config.issuer[0]) {
                    _state = AUTH_REQUESTING_CODE;
                } else {
                    _state = AUTH_IDLE;
                }
                _storage->putUint32(NS, "state", static_cast<uint32_t>(_state));
            }
        }
#ifndef OAUTH2_TESTING
        else if (_tokenExpiry > 0) {
            OAUTH_LOG(1, "Boot: token valid for %lus",
                          _tokenExpiry - nowSec);
        }
#endif
    }
}

// ── Token management ───────────────────────────────────────────────

void OAuth2DeviceFlow::refreshToken() {
    if (_refreshToken[0] == '\0') {
        strlcpy(_lastError, "No refresh token", sizeof(_lastError));
        setState(AUTH_ERROR);
        return;
    }
    exchangeRefreshToken();
}

void OAuth2DeviceFlow::clearTokens() {
#ifndef OAUTH2_TESTING
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
    _accessToken[0] = '\0';
    _refreshToken[0] = '\0';
    _tokenExpiry = 0;
    _refreshTokenExpiry = 0;
    _hasTokens = false;
    _deviceCode[0] = '\0';
    _userCode[0] = '\0';
    _verificationUri[0] = '\0';
    _verificationUriComplete[0] = '\0';
    _deviceCodeExpiry = 0;
    if (_storage) {
        _storage->remove(NS, "access_token");
        _storage->remove(NS, "refresh_token");
        _storage->remove(NS, "token_expiry");
        _storage->remove(NS, "refresh_exp");
        _storage->putBool(NS, "has_tokens", false);
        _storage->remove(NS, "device_code");
        _storage->remove(NS, "user_code");
        _storage->remove(NS, "ver_uri");
        _storage->remove(NS, "ver_uri_full");
    }
    setState(AUTH_IDLE);
#ifndef OAUTH2_TESTING
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
#endif
}

void OAuth2DeviceFlow::clearConfig() {
#ifndef OAUTH2_TESTING
    xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
    _config = {};
    _cfgIssuer[0] = '\0';
    _cfgClientId[0] = '\0';
    _cfgScope[0] = '\0';
    if (_storage) {
        _storage->remove(NS, "issuer");
        _storage->remove(NS, "client_id");
        _storage->remove(NS, "scope");
        _storage->remove(NS, "timeout_ms");
    }
#ifndef OAUTH2_TESTING
    xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
#endif
}

// ── Background task ────────────────────────────────────────────────

void OAuth2DeviceFlow::pollingTaskEntry(void* param) {
    static_cast<OAuth2DeviceFlow*>(param)->pollingTaskLoop();
}

void OAuth2DeviceFlow::pollingTaskLoop() {
    for (;;) {
#ifndef OAUTH2_TESTING
        xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
        switch (_state) {
            case AUTH_REQUESTING_CODE: requestDeviceCode(); break;
            case AUTH_DISPLAYING_CODE: setState(AUTH_POLLING); break;
            case AUTH_POLLING: {
                if (nowMs() - _flowStartTime > _config.timeoutMs ||
                    (_deviceCodeExpiry > 0 && nowMs() > _deviceCodeExpiry)) {
                    strlcpy(_lastError, "Timed out", sizeof(_lastError));
                    setState(AUTH_ERROR);
                    break;
                }
#ifndef OAUTH2_TESTING
                xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
                vTaskDelay(pdMS_TO_TICKS(_pollInterval));
                xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
                pollToken();
                break;
            }
            case AUTHENTICATED: {
                // _tokenExpiry is epoch seconds (from JWT exp claim or expires_in fallback)
                if (!_hasTokens) {
                    // Shouldn't happen — but guard against edge case
                    setState(AUTH_IDLE);
                    break;
                }
                if (_refreshToken[0] == '\0') {
                    // No refresh token — sleep until token expires, then wait for user re-auth
                    uint32_t nowSec = static_cast<uint32_t>(time(NULL));
                    uint32_t delayMs = 3600000;  // Default 1 hour
                    if (_tokenExpiry > 0 && _tokenExpiry > nowSec) {
                        delayMs = (_tokenExpiry - nowSec) * 1000;
#ifndef OAUTH2_TESTING
                        OAUTH_LOG(1, "No refresh token, token expires in %lus",
                                      _tokenExpiry - nowSec);
#endif
                    } else {
                        // Token already expired — nothing to do, wait for dashboard re-auth
#ifndef OAUTH2_TESTING
                        OAUTH_LOG(1, "Token expired, no refresh token — waiting for re-auth");
#endif
                        delayMs = 60000;  // Check again in 1 minute
                    }
#ifndef OAUTH2_TESTING
                    xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
                    vTaskDelay(pdMS_TO_TICKS(delayMs));
                    xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
#endif
                    break;
                }
                // Have refresh token — sleep until halfway to expiry, then refresh
                uint32_t delayMs = 3600000;  // Default 1 hour
                if (_tokenExpiry > 0) {
                    uint32_t nowSec = static_cast<uint32_t>(time(NULL));
                    if (_tokenExpiry > nowSec) {
                        uint32_t remainingSec = _tokenExpiry - nowSec;
                        delayMs = (remainingSec / 2) * 1000;  // Wake at halfway
#ifndef OAUTH2_TESTING
                        OAUTH_LOG(1, "Token valid for %lus, sleeping %lus before refresh",
                                      remainingSec, remainingSec / 2);
#endif
                    } else {
                        delayMs = 0;  // Already expired, refresh immediately
#ifndef OAUTH2_TESTING
                        OAUTH_LOG(1, "Token expired, refreshing now");
#endif
                    }
                }
#ifndef OAUTH2_TESTING
                xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
                vTaskDelay(pdMS_TO_TICKS(delayMs));
                xSemaphoreTake(static_cast<SemaphoreHandle_t>(_mutex), portMAX_DELAY);
                OAUTH_LOG(1, "Background refresh starting");
                exchangeRefreshToken();
                if (_hasTokens) {
                    OAUTH_LOG(1, "Background refresh succeeded");
                } else {
                    // Refresh failed — stay AUTHENTICATED, user must re-auth via dashboard
                    OAUTH_LOG(1, "Refresh failed — re-authentication required");
                }
                break;  // Loop back to re-evaluate state
#else
                return;
#endif
            }
            case AUTH_ERROR:
#ifndef OAUTH2_TESTING
                // If config is valid, auto-recover by restarting device code flow
                if (_config.issuer && _config.issuer[0]) {
                    OAUTH_LOG(1, "Error state with valid config, restarting device code flow");
                    // Clear tokens directly (mutex already held)
                    _accessToken[0] = '\0';
                    _refreshToken[0] = '\0';
                    _tokenExpiry = 0;
                    _refreshTokenExpiry = 0;
                    _hasTokens = false;
                    if (_storage) {
                        _storage->remove(NS, "access_token");
                        _storage->remove(NS, "refresh_token");
                        _storage->remove(NS, "token_expiry");
                        _storage->remove(NS, "refresh_exp");
                        _storage->putBool(NS, "has_tokens", false);
                    }
                    setState(AUTH_REQUESTING_CODE);
                    _flowStartTime = nowMs();
                } else {
                    xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
                    vTaskSuspend(NULL);
                    continue;
                }
#endif
                break;
            default: break;
        }
#ifndef OAUTH2_TESTING
        xSemaphoreGive(static_cast<SemaphoreHandle_t>(_mutex));
        vTaskDelay(pdMS_TO_TICKS(100));
#else
        if (_state == AUTH_POLLING || _state == AUTHENTICATED ||
            _state == AUTH_ERROR || _state == AUTH_IDLE) return;
#endif
    }
}

// ── Device code request ────────────────────────────────────────────

void OAuth2DeviceFlow::requestDeviceCode() {
    char url[512];
    snprintf(url, sizeof(url), "%s/application/o/device/", _config.issuer);
    char body[512];
    snprintf(body, sizeof(body), "client_id=%s&scope=%s", _config.clientId, _config.scope);

#ifndef OAUTH2_TESTING
    OAUTH_LOG(1, "Device code request: scope=%s", _config.scope);
#endif
    OAuth2HttpResponse resp = requestInternal("POST", url, nullptr, body);

#ifndef OAUTH2_TESTING
    OAUTH_LOG(1, "Device code request: status=%d", resp.statusCode);
    char respBuf[512] = {};
    serializeJson(resp.body, respBuf, sizeof(respBuf));
    OAUTH_LOG(1, "Response: %.400s", respBuf);
#endif

    if (resp.statusCode == 0) { strlcpy(_lastError, "Network error", sizeof(_lastError)); setState(AUTH_ERROR); return; }
    if (resp.statusCode != 200) { strlcpy(_lastError, "Device code request failed", sizeof(_lastError)); setState(AUTH_ERROR); return; }

    strlcpy(_deviceCode, resp.body["device_code"] | "", sizeof(_deviceCode));
    strlcpy(_userCode, resp.body["user_code"] | "", sizeof(_userCode));
    strlcpy(_verificationUri, resp.body["verification_uri"] | "", sizeof(_verificationUri));
    strlcpy(_verificationUriComplete, resp.body["verification_uri_complete"] | "", sizeof(_verificationUriComplete));
    _pollInterval = static_cast<uint16_t>(resp.body["interval"] | 5000);
    int expires_in = resp.body["expires_in"] | 60;
    _deviceCodeExpiry = nowMs() + (expires_in * 1000);

    if (_deviceCode[0] == '\0' || _userCode[0] == '\0') {
        strlcpy(_lastError, "Invalid device code response", sizeof(_lastError));
        setState(AUTH_ERROR);
        return;
    }
    saveDeviceCodeInfo();
    setState(AUTH_DISPLAYING_CODE);
}

// ── Token polling ──────────────────────────────────────────────────

static void urlEncode(char* dest, size_t destLen, const char* src) {
    size_t j = 0;
    for (size_t i = 0; src[i] && j < destLen - 4; i++) {
        unsigned char c = (unsigned char)src[i];
        if (c == '-' || c == '_' || c == '.' || c == '~' ||
            (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
            dest[j++] = c;
        } else {
            snprintf(dest + j, destLen - j, "%%%02X", c);
            j += 3;
        }
    }
    dest[j] = '\0';
}

void OAuth2DeviceFlow::pollToken() {
    char url[512];
    snprintf(url, sizeof(url), "%s/application/o/token/", _config.issuer);

    // URL-encode device_code — it contains special characters
    char encodedDeviceCode[512];
    urlEncode(encodedDeviceCode, sizeof(encodedDeviceCode), _deviceCode);

    char body[1536];
    snprintf(body, sizeof(body),
             "grant_type=urn%%3Aietf%%3Aparams%%3Aoauth%%3Agrant-type%%3Adevice_code"
             "&device_code=%s&client_id=%s", encodedDeviceCode, _config.clientId);

#ifndef OAUTH2_TESTING
    OAUTH_LOG(1, "Token poll URL: %s", url);
    OAUTH_LOG(1, "Token poll body: %.200s", body);
#endif

    OAuth2HttpResponse resp = requestInternal("POST", url, nullptr, body);

#ifndef OAUTH2_TESTING
    OAUTH_LOG(1, "Token poll: status=%d", resp.statusCode);
    char respBuf[512] = {};
    serializeJson(resp.body, respBuf, sizeof(respBuf));
    OAUTH_LOG(1, "Token response: %.400s", respBuf);
#endif

    if (resp.statusCode == 0) { strlcpy(_lastError, "Network error", sizeof(_lastError)); setState(AUTH_ERROR); return; }

    const char* error = resp.body["error"] | "";
    if (error[0] != '\0') {
        if (strcmp(error, "authorization_pending") == 0) return;
        if (strcmp(error, "slow_down") == 0) {
            _pollInterval += 5000;
            if (_storage) _storage->putUint32(NS, "poll_int", _pollInterval);
            return;
        }
        strlcpy(_lastError, resp.body["error_description"] | error, sizeof(_lastError));
        setState(AUTH_ERROR);
        return;
    }

    const char* accessToken = resp.body["access_token"] | "";
    const char* refreshToken = resp.body["refresh_token"] | "";
    int expiresIn = resp.body["expires_in"] | 0;
    int refreshExpiresIn = resp.body["refresh_expires_in"] | 0;
    if (accessToken[0] == '\0') { strlcpy(_lastError, "No access token", sizeof(_lastError)); setState(AUTH_ERROR); return; }

    strlcpy(_accessToken, accessToken, sizeof(_accessToken));
    strlcpy(_refreshToken, refreshToken, sizeof(_refreshToken));

    // Validate JWT exp claim — prefer it over expires_in
    // Store as epoch seconds (not millis) to avoid uint32 overflow
    uint32_t jwtExp = parseJwtExp(accessToken);
    if (jwtExp > 0) {
        _tokenExpiry = jwtExp;
    } else {
        _tokenExpiry = static_cast<uint32_t>(time(NULL)) + expiresIn;
    }
    _refreshTokenExpiry = (refreshExpiresIn > 0)
        ? static_cast<uint32_t>(time(NULL)) + refreshExpiresIn : 0;
    _hasTokens = true;
#ifndef OAUTH2_TESTING
    if (_refreshToken[0] == '\0') {
        OAUTH_LOG(1, "No refresh token in response — token will require re-auth on expiry");
    } else if (_refreshTokenExpiry > 0) {
        OAUTH_LOG(1, "Refresh token received (expires in %ds)", refreshExpiresIn);
    } else {
        OAUTH_LOG(1, "Refresh token received (no expiry)");
    }
#endif
    saveTokens();
    setState(AUTHENTICATED);
}

// ── Token refresh ──────────────────────────────────────────────────

void OAuth2DeviceFlow::exchangeRefreshToken() {
    char url[512];
    snprintf(url, sizeof(url), "%s/application/o/token/", _config.issuer);
    char body[1024];
    snprintf(body, sizeof(body), "grant_type=refresh_token&refresh_token=%s&client_id=%s",
             _refreshToken, _config.clientId);

#ifndef OAUTH2_TESTING
    OAUTH_LOG(1, "Refreshing token via %s", url);
#endif
    OAuth2HttpResponse resp = requestInternal("POST", url, nullptr, body);
    if (resp.statusCode == 0 || resp.statusCode != 200) {
#ifndef OAUTH2_TESTING
        OAUTH_LOG(1, "Token refresh failed: status=%d", resp.statusCode);
#endif
        strlcpy(_lastError, "Token refresh failed", sizeof(_lastError));
        _hasTokens = false;
        setState(AUTH_ERROR);
        return;
    }

    const char* accessToken = resp.body["access_token"] | "";
    const char* refreshToken = resp.body["refresh_token"] | "";
    int expiresIn = resp.body["expires_in"] | 0;
    int refreshExpiresIn = resp.body["refresh_expires_in"] | 0;
    if (accessToken[0] == '\0') { strlcpy(_lastError, "No token in refresh", sizeof(_lastError)); _hasTokens = false; setState(AUTH_ERROR); return; }

    strlcpy(_accessToken, accessToken, sizeof(_accessToken));
    if (refreshToken[0] != '\0') strlcpy(_refreshToken, refreshToken, sizeof(_refreshToken));

    // Validate JWT exp claim — prefer it over expires_in
    // Store as epoch seconds (not millis) to avoid uint32 overflow
    uint32_t jwtExp = parseJwtExp(accessToken);
    if (jwtExp > 0) {
        _tokenExpiry = jwtExp;
    } else {
        _tokenExpiry = static_cast<uint32_t>(time(NULL)) + expiresIn;
    }
    _refreshTokenExpiry = (refreshExpiresIn > 0)
        ? static_cast<uint32_t>(time(NULL)) + refreshExpiresIn : 0;
    _hasTokens = true;
#ifndef OAUTH2_TESTING
    uint32_t nowSec = static_cast<uint32_t>(time(NULL));
    uint32_t accessRemaining = _tokenExpiry > nowSec ? _tokenExpiry - nowSec : 0;
    uint32_t refreshRemaining = _refreshTokenExpiry > nowSec ? _refreshTokenExpiry - nowSec : 0;
    if (_refreshTokenExpiry > 0) {
        OAUTH_LOG(1, "Token refreshed, access expires in %lus, refresh expires in %lus", accessRemaining, refreshRemaining);
    } else {
        OAUTH_LOG(1, "Token refreshed, access expires in %lus", accessRemaining);
    }
#endif
    saveTokens();
}

// ── JWT exp claim parsing ──────────────────────────────────────────

static uint32_t parseJwtExp(const char* jwt) {
    // JWT format: header.payload.signature
    // Find the second '.' to isolate the payload
    const char* dot1 = strchr(jwt, '.');
    if (!dot1) return 0;
    const char* dot2 = strchr(dot1 + 1, '.');
    if (!dot2) return 0;

    // Base64url decode the payload
    const char* payloadB64 = dot1 + 1;
    int payloadB64Len = dot2 - payloadB64;

    // Base64url → base64: replace - with + and _ with /
    char* b64 = (char*)malloc(payloadB64Len + 4);
    if (!b64) return 0;
    memcpy(b64, payloadB64, payloadB64Len);
    b64[payloadB64Len] = '\0';
    for (int i = 0; i < payloadB64Len; i++) {
        if (b64[i] == '-') b64[i] = '+';
        else if (b64[i] == '_') b64[i] = '/';
    }
    // Add padding
    int pad = (4 - (payloadB64Len % 4)) % 4;
    for (int i = 0; i < pad; i++) b64[payloadB64Len + i] = '=';
    b64[payloadB64Len + pad] = '\0';

    // Decode
    int decodedLen = ((payloadB64Len + pad) * 3) / 4;
    uint8_t* decoded = (uint8_t*)malloc(decodedLen + 1);
    if (!decoded) { free(b64); return 0; }

    // Simple base64 decode
    static const char* tbl = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    int j = 0;
    for (int i = 0; i < payloadB64Len + pad; i += 4) {
        int a = strchr(tbl, b64[i]) - tbl;
        int b = strchr(tbl, b64[i+1]) - tbl;
        int c = (b64[i+2] == '=') ? 0 : (strchr(tbl, b64[i+2]) - tbl);
        int d = (b64[i+3] == '=') ? 0 : (strchr(tbl, b64[i+3]) - tbl);
        decoded[j++] = (a << 2) | (b >> 4);
        if (b64[i+2] != '=') decoded[j++] = ((b & 0xF) << 4) | (c >> 2);
        if (b64[i+3] != '=') decoded[j++] = ((c & 0x3) << 6) | d;
    }
    decoded[j] = '\0';
    free(b64);

    // Parse JSON to find "exp"
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, (const char*)decoded);
    free(decoded);
    if (err) return 0;

    uint32_t exp = doc["exp"] | 0U;
    return exp;
}

// Ensure token is valid — refresh if expired. Returns true if token available.
bool OAuth2DeviceFlow::ensureValidToken() {
    if (!_hasTokens || _accessToken[0] == '\0') return false;

    // Check stored expiry (epoch seconds)
    // Don't refresh here — the background polling task owns token lifecycle.
    return static_cast<uint32_t>(time(NULL)) < _tokenExpiry;
}

// ── esp_http_client proxy ──────────────────────────────────────────

void OAuth2DeviceFlow::setTransport(void* client) {
    _transport = client;
    _pendingStatus = 0;
}

int OAuth2DeviceFlow::open(int write_len) {
    _pendingStatus = 0;
#ifndef OAUTH2_TESTING
    auto client = static_cast<esp_http_client_handle_t>(_transport);
    if (client) {
        // Ensure token is valid before injecting
        ensureValidToken();

        if (_hasTokens && _accessToken[0] != '\0') {
            char authVal[2200];
            snprintf(authVal, sizeof(authVal), "Bearer %s", _accessToken);
            esp_http_client_set_header(client, "Authorization", authVal);
        }
        return esp_http_client_open(client, write_len);
    }
#endif
    return -1;
}

int OAuth2DeviceFlow::write(const void* data, int len) {
#ifndef OAUTH2_TESTING
    auto client = static_cast<esp_http_client_handle_t>(_transport);
    if (client) return esp_http_client_write(client, static_cast<const char*>(data), len);
#endif
    return -1;
}

int OAuth2DeviceFlow::fetch_headers() {
#ifndef OAUTH2_TESTING
    auto client = static_cast<esp_http_client_handle_t>(_transport);
    if (!client) return -1;
    esp_http_client_fetch_headers(client);
    int status = esp_http_client_get_status_code(client);

    if (status == 401) {
        // Don't refresh here — the background polling task owns token lifecycle.
        esp_http_client_close(client);
        _pendingStatus = -401;
        return -401;
    }
    return status;
#endif
    return -1;
}

int OAuth2DeviceFlow::get_status_code() {
    if (_pendingStatus != 0) return _pendingStatus;
#ifndef OAUTH2_TESTING
    auto client = static_cast<esp_http_client_handle_t>(_transport);
    if (client) return esp_http_client_get_status_code(client);
#endif
    return 0;
}

int OAuth2DeviceFlow::read(void* buf, int len) {
#ifndef OAUTH2_TESTING
    auto client = static_cast<esp_http_client_handle_t>(_transport);
    if (client) return esp_http_client_read(client, static_cast<char*>(buf), len);
#endif
    return -1;
}

void OAuth2DeviceFlow::close() {
    _pendingStatus = 0;
#ifndef OAUTH2_TESTING
    auto client = static_cast<esp_http_client_handle_t>(_transport);
    if (client) esp_http_client_close(client);
#endif
}

// ── One-shot convenience (internal use + auth server requests) ─────

OAuth2HttpResponse OAuth2DeviceFlow::doWithRetry(const char* method, const char* path,
                                                  const char* body) {
    OAuth2HttpResponse result;
    result.statusCode = 0;
    if (!_config.issuer || _config.issuer[0] == '\0') {
        strlcpy(_lastError, "Not configured", sizeof(_lastError));
        return result;
    }
    char url[512];
    snprintf(url, sizeof(url), "%s%s", _config.issuer, path);

    char authHeader[2200] = {};
    if (_hasTokens && _accessToken[0] != '\0')
        snprintf(authHeader, sizeof(authHeader), "Bearer %s", _accessToken);

    result = requestInternal(method, url, authHeader[0] ? authHeader : nullptr, body);

    // 401 on pass-through: return it to the caller (upload skips this chunk).
    // Don't refresh here — the background polling task owns token lifecycle.
    // Refreshing here races with the polling task and can clobber its state.
    return result;
}

OAuth2HttpResponse OAuth2DeviceFlow::get(const char* path) { return doWithRetry("GET", path, nullptr); }
OAuth2HttpResponse OAuth2DeviceFlow::post(const char* path, const char* body) { return doWithRetry("POST", path, body); }
OAuth2HttpResponse OAuth2DeviceFlow::put(const char* path, const char* body) { return doWithRetry("PUT", path, body); }
OAuth2HttpResponse OAuth2DeviceFlow::patch(const char* path, const char* body) { return doWithRetry("PATCH", path, body); }
OAuth2HttpResponse OAuth2DeviceFlow::del(const char* path) { return doWithRetry("DELETE", path, nullptr); }

// ── Internal HTTP (esp_http_client or test mock) ───────────────────

OAuth2HttpResponse OAuth2DeviceFlow::requestInternal(const char* method, const char* url,
                                                      const char* extraHeaders, const char* body) {
    OAuth2HttpResponse result;
    result.statusCode = 0;

#ifdef OAUTH2_TESTING
    if (mockHttpResponseReady) {
        result.statusCode = mockHttpStatus;
        if (mockHttpBody[0] != '\0') deserializeJson(result.body, mockHttpBody);
        mockHttpResponseReady = false;
    }
    return result;
#else
    esp_http_client_method_t httpMethod = HTTP_METHOD_GET;
    if (strcmp(method, "POST") == 0) httpMethod = HTTP_METHOD_POST;
    else if (strcmp(method, "PUT") == 0) httpMethod = HTTP_METHOD_PUT;
    else if (strcmp(method, "PATCH") == 0) httpMethod = HTTP_METHOD_PATCH;
    else if (strcmp(method, "DELETE") == 0) httpMethod = HTTP_METHOD_DELETE;

    esp_http_client_config_t config = {};
    config.url = url;
    config.method = httpMethod;
    config.timeout_ms = 15000;
    config.buffer_size = 4096;
    config.crt_bundle_attach = esp_crt_bundle_attach;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return result;

    if (body && (httpMethod == HTTP_METHOD_POST || httpMethod == HTTP_METHOD_PUT || httpMethod == HTTP_METHOD_PATCH))
        esp_http_client_set_header(client, "Content-Type", "application/x-www-form-urlencoded");
    if (extraHeaders && extraHeaders[0] != '\0')
        esp_http_client_set_header(client, "Authorization", extraHeaders);

    esp_err_t err;
    if (body && (httpMethod == HTTP_METHOD_POST || httpMethod == HTTP_METHOD_PUT || httpMethod == HTTP_METHOD_PATCH)) {
        err = esp_http_client_open(client, strlen(body));
        if (err == ESP_OK) {
            esp_http_client_write(client, body, strlen(body));
            esp_http_client_fetch_headers(client);
            result.statusCode = esp_http_client_get_status_code(client);
        }
    } else {
        err = esp_http_client_open(client, 0);
        if (err == ESP_OK) {
            esp_http_client_fetch_headers(client);
            result.statusCode = esp_http_client_get_status_code(client);
        }
    }

    if (err == ESP_OK && result.statusCode > 0) {
        // Read response body — heap allocate to avoid stack overflow on FreeRTOS tasks
        char* buf = (char*)pvPortMalloc(4096);
        if (buf) {
            int totalRead = 0;
            while (totalRead < 4095) {
                int n = esp_http_client_read(client, buf + totalRead, 4095 - totalRead);
                if (n <= 0) break;
                totalRead += n;
            }
            if (totalRead > 0) {
                buf[totalRead] = '\0';
                deserializeJson(result.body, buf);
#ifndef OAUTH2_TESTING
                OAUTH_LOG(1, "Read %d bytes of response", totalRead);
#endif
            }
            vPortFree(buf);
        }
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return result;
#endif
}
