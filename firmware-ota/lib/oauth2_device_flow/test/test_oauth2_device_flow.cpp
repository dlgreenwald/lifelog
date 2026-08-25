// OAuth2 Device Code Flow — native tests
// Compiles under `pio test -e test` (native, no ESP32 hardware).
// Uses OAUTH2_TESTING to inject mock time and HTTP responses.
// Functions called from test_all.cpp main().

#include <unity.h>
#include <cstring>
#include <map>
#include <string>

#define OAUTH2_TESTING 1
#include <oauth2_device_flow.h>

// ── Mock time ──────────────────────────────────────────────────────

uint32_t _oauth2_test_mock_time = 10000;

static void oauth2AdvanceTime(uint32_t ms) {
    _oauth2_test_mock_time += ms;
}

// ── Mock storage ───────────────────────────────────────────────────

static std::map<std::string, std::string> store_strings;
static std::map<std::string, uint32_t> store_uints;
static std::map<std::string, bool> store_bools;

static void mockPutString(const char* ns, const char* key, const char* value) {
    std::string k = std::string(ns) + ":" + key;
    store_strings[k] = value ? value : "";
}

static const char* mockGetString(const char* ns, const char* key, const char* def) {
    std::string k = std::string(ns) + ":" + key;
    auto it = store_strings.find(k);
    if (it != store_strings.end()) return it->second.c_str();
    return def ? def : "";
}

static void mockPutUint32(const char* ns, const char* key, uint32_t value) {
    std::string k = std::string(ns) + ":" + key;
    store_uints[k] = value;
}

static uint32_t mockGetUint32(const char* ns, const char* key, uint32_t def) {
    std::string k = std::string(ns) + ":" + key;
    auto it = store_uints.find(k);
    return it != store_uints.end() ? it->second : def;
}

static void mockPutBool(const char* ns, const char* key, bool value) {
    std::string k = std::string(ns) + ":" + key;
    store_bools[k] = value;
}

static bool mockGetBool(const char* ns, const char* key, bool def) {
    std::string k = std::string(ns) + ":" + key;
    auto it = store_bools.find(k);
    return it != store_bools.end() ? it->second : def;
}

static void mockRemove(const char* ns, const char* key) {
    std::string k = std::string(ns) + ":" + key;
    store_strings.erase(k);
    store_uints.erase(k);
    store_bools.erase(k);
}

static void mockClearNamespace(const char* ns) {
    std::string prefix = std::string(ns) + ":";
    for (auto it = store_strings.begin(); it != store_strings.end(); ) {
        if (it->first.compare(0, prefix.size(), prefix) == 0)
            it = store_strings.erase(it);
        else ++it;
    }
    for (auto it = store_uints.begin(); it != store_uints.end(); ) {
        if (it->first.compare(0, prefix.size(), prefix) == 0)
            it = store_uints.erase(it);
        else ++it;
    }
    for (auto it = store_bools.begin(); it != store_bools.end(); ) {
        if (it->first.compare(0, prefix.size(), prefix) == 0)
            it = store_bools.erase(it);
        else ++it;
    }
}

static OAuth2Storage mockStorage = {
    mockPutString, mockGetString,
    mockPutUint32, mockGetUint32,
    mockPutBool, mockGetBool,
    mockRemove, mockClearNamespace
};

// ── Helpers ────────────────────────────────────────────────────────

static OAuth2DeviceFlow oauth2Flow;

static void oauth2ResetAll() {
    _oauth2_test_mock_time = 10000;
    store_strings.clear();
    store_uints.clear();
    store_bools.clear();
    oauth2Flow = OAuth2DeviceFlow();
}

static OAuth2Config oauth2TestConfig() {
    OAuth2Config cfg;
    cfg.issuer = "https://auth.example.com";
    cfg.clientId = "test-client";
    cfg.scope = "openid offline_access";
    cfg.timeoutMs = 600000;
    return cfg;
}

static void oauth2SetupToPolling(OAuth2DeviceFlow& f) {
    f._testSetHttpResponse(200,
        "{\"device_code\":\"abc123\","
        "\"user_code\":\"ABCD-1234\","
        "\"verification_uri\":\"https://auth.example.com/device\","
        "\"verification_uri_complete\":\"https://auth.example.com/device?user_code=ABCD-1234\","
        "\"interval\":5}");
    f.start();
}

// ── Registration flow tests ────────────────────────────────────────

void test_oauth2_initial_state_is_idle() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    TEST_ASSERT_EQUAL(AUTH_IDLE, oauth2Flow.getState());
}

void test_oauth2_start_transitions_to_requesting_code() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());
    oauth2Flow.start();
    TEST_ASSERT_EQUAL(AUTH_ERROR, oauth2Flow.getState());
}

void test_oauth2_device_code_request_success() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);

    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());
    TEST_ASSERT_EQUAL_STRING("ABCD-1234", oauth2Flow.getUserCode());
    TEST_ASSERT_EQUAL_STRING("https://auth.example.com/device", oauth2Flow.getVerificationUri());
    TEST_ASSERT_EQUAL_STRING("https://auth.example.com/device?user_code=ABCD-1234",
                             oauth2Flow.getVerificationUriComplete());
}

void test_oauth2_device_code_request_network_error() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());
    oauth2Flow.start();
    TEST_ASSERT_EQUAL(AUTH_ERROR, oauth2Flow.getState());
    TEST_ASSERT_EQUAL_STRING("Network error", oauth2Flow.getLastError());
}

void test_oauth2_poll_authorization_pending() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());

    oauth2Flow._testSetHttpResponse(200, "{\"error\":\"authorization_pending\"}");
    oauth2Flow.pollOnce();
    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());
}

void test_oauth2_poll_slow_down() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());

    oauth2Flow._testSetHttpResponse(200, "{\"error\":\"slow_down\"}");
    oauth2Flow.pollOnce();

    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());
    uint32_t storedInterval = mockGetUint32("oauth2", "poll_int", 5000);
    TEST_ASSERT_GREATER_THAN(5000, storedInterval);
}

void test_oauth2_poll_success() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());

    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_xyz\","
        "\"refresh_token\":\"rt_xyz\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();

    TEST_ASSERT_EQUAL(AUTHENTICATED, oauth2Flow.getState());
    TEST_ASSERT_TRUE(oauth2Flow.hasValidToken());
    TEST_ASSERT_GREATER_THAN(0, oauth2Flow.getTokenExpiresInSeconds());
}

void test_oauth2_poll_expired_token_error() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);

    oauth2Flow._testSetHttpResponse(200, "{\"error\":\"expired_token\"}");
    oauth2Flow.pollOnce();

    TEST_ASSERT_EQUAL(AUTH_ERROR, oauth2Flow.getState());
    TEST_ASSERT_EQUAL_STRING("expired_token", oauth2Flow.getLastError());
}

void test_oauth2_poll_access_denied() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);

    oauth2Flow._testSetHttpResponse(200, "{\"error\":\"access_denied\"}");
    oauth2Flow.pollOnce();

    TEST_ASSERT_EQUAL(AUTH_ERROR, oauth2Flow.getState());
    TEST_ASSERT_EQUAL_STRING("access_denied", oauth2Flow.getLastError());
}

void test_oauth2_poll_timeout() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    OAuth2Config cfg = oauth2TestConfig();
    cfg.timeoutMs = 30000;
    oauth2Flow.configure(cfg);

    oauth2SetupToPolling(oauth2Flow);

    oauth2AdvanceTime(31000);

    oauth2Flow._testSetHttpResponse(200, "{\"error\":\"authorization_pending\"}");
    oauth2Flow.pollOnce();

    TEST_ASSERT_EQUAL(AUTH_ERROR, oauth2Flow.getState());
    TEST_ASSERT_EQUAL_STRING("Timed out", oauth2Flow.getLastError());
}

void test_oauth2_start_after_error_retries() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());
    oauth2Flow.start();
    TEST_ASSERT_EQUAL(AUTH_ERROR, oauth2Flow.getState());

    oauth2Flow._testSetHttpResponse(200,
        "{\"device_code\":\"abc123\","
        "\"user_code\":\"XXXX-YYYY\","
        "\"verification_uri\":\"https://auth.example.com/device\","
        "\"interval\":5}");
    oauth2Flow.start();
    TEST_ASSERT_EQUAL(AUTH_POLLING, oauth2Flow.getState());
    TEST_ASSERT_EQUAL_STRING("XXXX-YYYY", oauth2Flow.getUserCode());
}

// ── Token management tests ─────────────────────────────────────────

void test_oauth2_has_valid_token() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    TEST_ASSERT_FALSE(oauth2Flow.hasValidToken());

    oauth2SetupToPolling(oauth2Flow);

    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_xyz\","
        "\"refresh_token\":\"rt_xyz\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();
    TEST_ASSERT_TRUE(oauth2Flow.hasValidToken());

    oauth2AdvanceTime(3601000);
    TEST_ASSERT_FALSE(oauth2Flow.hasValidToken());
    TEST_ASSERT_EQUAL(0, oauth2Flow.getTokenExpiresInSeconds());
}

void test_oauth2_clear_tokens() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_xyz\","
        "\"refresh_token\":\"rt_xyz\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();
    TEST_ASSERT_TRUE(oauth2Flow.hasValidToken());

    oauth2Flow.clearTokens();
    TEST_ASSERT_FALSE(oauth2Flow.hasValidToken());
    TEST_ASSERT_EQUAL(AUTH_IDLE, oauth2Flow.getState());
}

void test_oauth2_token_refresh() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_old\","
        "\"refresh_token\":\"rt_old\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();
    TEST_ASSERT_TRUE(oauth2Flow.hasValidToken());

    oauth2AdvanceTime(3601000);
    TEST_ASSERT_FALSE(oauth2Flow.hasValidToken());

    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_new\","
        "\"refresh_token\":\"rt_new\","
        "\"expires_in\":3600}");
    oauth2Flow.refreshToken();
    TEST_ASSERT_TRUE(oauth2Flow.hasValidToken());
    TEST_ASSERT_EQUAL(AUTHENTICATED, oauth2Flow.getState());
}

void test_oauth2_storage_roundtrip() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_xyz\","
        "\"refresh_token\":\"rt_xyz\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();

    TEST_ASSERT_EQUAL_STRING("at_xyz", mockGetString("oauth2", "access_token", ""));
    TEST_ASSERT_EQUAL_STRING("rt_xyz", mockGetString("oauth2", "refresh_token", ""));

    OAuth2DeviceFlow flow2;
    flow2.begin(&mockStorage);
    TEST_ASSERT_TRUE(flow2.hasValidToken());
}

void test_oauth2_configure_overwrites_defaults() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);

    OAuth2Config cfg;
    cfg.issuer = "https://custom.example.com";
    cfg.clientId = "custom-client";
    cfg.scope = "openid";
    cfg.timeoutMs = 120000;
    oauth2Flow.configure(cfg);

    TEST_ASSERT_EQUAL_STRING("https://custom.example.com", mockGetString("oauth2", "issuer", ""));
    TEST_ASSERT_EQUAL_STRING("custom-client", mockGetString("oauth2", "client_id", ""));
    TEST_ASSERT_EQUAL_STRING("openid", mockGetString("oauth2", "scope", ""));

    OAuth2DeviceFlow flow2;
    flow2.begin(&mockStorage);
    TEST_ASSERT_EQUAL_STRING("https://custom.example.com", mockGetString("oauth2", "issuer", ""));
}

// ── HTTP proxy tests ───────────────────────────────────────────────

void test_oauth2_get_returns_zero_when_not_authenticated() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    OAuth2HttpResponse resp = oauth2Flow.get("/api/test");
    TEST_ASSERT_EQUAL(0, resp.statusCode);
}

void test_oauth2_post_injects_auth_header() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_xyz\","
        "\"refresh_token\":\"rt_xyz\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();

    oauth2Flow._testSetHttpResponse(200, "{\"status\":\"ok\"}");
    OAuth2HttpResponse resp = oauth2Flow.post("/api/upload", "data");
    TEST_ASSERT_EQUAL(200, resp.statusCode);
}

void test_oauth2_post_retries_on_401() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_old\","
        "\"refresh_token\":\"rt_old\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();

    oauth2Flow._testSetHttpResponse(401, "");
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_new\","
        "\"refresh_token\":\"rt_new\","
        "\"expires_in\":3600}");
    oauth2Flow._testSetHttpResponse(200, "{\"status\":\"ok\"}");

    OAuth2HttpResponse resp = oauth2Flow.post("/api/upload", "data");
    TEST_ASSERT_EQUAL(200, resp.statusCode);
    TEST_ASSERT_TRUE(oauth2Flow.hasValidToken());
}

void test_oauth2_del_injects_auth_header() {
    oauth2ResetAll();
    oauth2Flow.begin(&mockStorage);
    oauth2Flow.configure(oauth2TestConfig());

    oauth2SetupToPolling(oauth2Flow);
    oauth2Flow._testSetHttpResponse(200,
        "{\"access_token\":\"at_xyz\","
        "\"refresh_token\":\"rt_xyz\","
        "\"expires_in\":3600}");
    oauth2Flow.pollOnce();

    oauth2Flow._testSetHttpResponse(200, "{\"status\":\"deleted\"}");
    OAuth2HttpResponse resp = oauth2Flow.del("/api/resource/1");
    TEST_ASSERT_EQUAL(200, resp.statusCode);
}
