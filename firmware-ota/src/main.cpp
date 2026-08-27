#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <RisalUI.h>
#include <WiFi.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <esp_task_wdt.h>
#include <esp_freertos_hooks.h>
#include <freertos/task.h>
#include <freertos/task_snapshot.h>
#include <ArduinoJson.h>
#include <mbedtls/platform.h>
#include <esp_heap_caps.h>
#include "config.h"
#include "settings.h"
#include "audio.h"
#include "i2s_fe.h"
#include "writer.h"
#include "upload.h"
#include "oauth2_client.h"
#ifdef BUILD_DEVELOPMENT
#define PROGRAM_NAME "LifeLog"
#include "taskman.h"
#endif

#define MAX_BOOT 3
#define HOSTNAME "LifeLog"

static Preferences prefs;
static const char* NS = "ota";
static TaskHandle_t feedTaskHandle = NULL;
static TaskHandle_t fetchTaskHandle = NULL;

// ── Device settings (defined in settings.h) ───────────────────────

DeviceSettings deviceSettings;
KnownNetwork knownNetworks[MAX_KNOWN_NETWORKS];
int knownNetworkCount = 0;

// ── Idle hook counters (per-core CPU usage) ────────────────────────

static volatile uint32_t idleCount0 = 0;
static volatile uint32_t idleCount1 = 0;

static bool idleHook0() { idleCount0++; return false; }
static bool idleHook1() { idleCount1++; return false; }

// ── Boot tracking ──────────────────────────────────────────────────

static void bootInit() {
    prefs.begin(NS, false);
    bool confirmed = prefs.getUChar("confirmed", 0);
    uint8_t boots = prefs.getUChar("boots", 0);
    if (confirmed) {
        ESP_LOGI("BOOT", "Firmware confirmed");
    } else {
        boots++;
        ESP_LOGW("BOOT", "Boot %d/%d (unconfirmed)", boots, MAX_BOOT);
        prefs.putUChar("boots", boots);
    }
    prefs.end();
}

static void bootConfirm() {
    prefs.begin(NS, false);
    prefs.putUChar("confirmed", 1);
    prefs.putUChar("boots", 0);
    prefs.end();
    ESP_LOGI("BOOT", "Firmware confirmed");
}

// ── NVS load/save ─────────────────────────────────────────────────

static void loadDeviceSettings() {
    Preferences p;
    p.begin("device", true);
    strlcpy(deviceSettings.hostname, p.getString("hostname", DEFAULT_HOSTNAME).c_str(), sizeof(deviceSettings.hostname));
    strlcpy(deviceSettings.serverHost, p.getString("server_host", DEFAULT_SERVER_HOST).c_str(), sizeof(deviceSettings.serverHost));
    deviceSettings.serverPort = p.getUShort("server_port", DEFAULT_SERVER_PORT);
    strlcpy(deviceSettings.serverPath, p.getString("server_path", DEFAULT_SERVER_PATH).c_str(), sizeof(deviceSettings.serverPath));
    strlcpy(deviceSettings.devicePassword, p.getString("device_pw", "").c_str(), sizeof(deviceSettings.devicePassword));
    strlcpy(deviceSettings.oauthIssuer, p.getString("oauth_issuer", "").c_str(), sizeof(deviceSettings.oauthIssuer));
    strlcpy(deviceSettings.oauthClientId, p.getString("oauth_client_id", "").c_str(), sizeof(deviceSettings.oauthClientId));
    strlcpy(deviceSettings.oauthScope, p.getString("oauth_scope", "openid offline_access").c_str(), sizeof(deviceSettings.oauthScope));
    knownNetworkCount = 0;
    String netsJson = p.getString("known_nets", "[]");
    p.end();
    JsonDocument doc;
    if (!deserializeJson(doc, netsJson) && doc.is<JsonArray>()) {
        for (JsonObject net : doc.as<JsonArray>()) {
            if (knownNetworkCount >= MAX_KNOWN_NETWORKS) break;
            strlcpy(knownNetworks[knownNetworkCount].ssid, net["ssid"] | "", 33);
            strlcpy(knownNetworks[knownNetworkCount].password, net["pw"] | "", 65);
            knownNetworkCount++;
        }
    }
    ESP_LOGI("WIFI", "Loaded %d known networks", knownNetworkCount);
}

static void saveDeviceSettings() {
    Preferences p;
    p.begin("device", false);
    p.putString("hostname", deviceSettings.hostname);
    p.putString("server_host", deviceSettings.serverHost);
    p.putUShort("server_port", deviceSettings.serverPort);
    p.putString("server_path", deviceSettings.serverPath);
    p.putString("device_pw", deviceSettings.devicePassword);
    p.putString("oauth_issuer", deviceSettings.oauthIssuer);
    p.putString("oauth_client_id", deviceSettings.oauthClientId);
    p.putString("oauth_scope", deviceSettings.oauthScope);
    JsonDocument doc;
    JsonArray arr = doc.to<JsonArray>();
    for (int i = 0; i < knownNetworkCount; i++) {
        JsonObject net = arr.add<JsonObject>();
        net["ssid"] = knownNetworks[i].ssid;
        net["pw"] = knownNetworks[i].password;
    }
    String netsJson;
    serializeJson(doc, netsJson);
    p.putString("known_nets", netsJson);
    p.end();
}

static void addKnownNetwork(const char* ssid, const char* password) {
    for (int i = 0; i < knownNetworkCount; i++) {
        if (strcmp(knownNetworks[i].ssid, ssid) == 0) {
            strlcpy(knownNetworks[i].password, password, 65);
            return;  // Updated existing
        }
    }
    if (knownNetworkCount < MAX_KNOWN_NETWORKS) {
        strlcpy(knownNetworks[knownNetworkCount].ssid, ssid, 33);
        strlcpy(knownNetworks[knownNetworkCount].password, password, 65);
        knownNetworkCount++;
    }
}

// ── RisalDash ──────────────────────────────────────────────────────

static RisalUI dash(HOSTNAME);

// Task priorities (higher = more important)
#define PRIO_AUDIO          5

// ── Dashboard widget state (bound by pointer) ──────────────────────
// Settings (editable)
static String cfgHostname;
static String cfgServerHost;
static String cfgServerPort;
static String cfgDevicePw;

// OAuth config (editable)
static String cfgOAuthIssuer;
static String cfgOAuthClientId;

// OAuth status (read-only)
static String statusAuthState;
static String statusUserCode;
static String statusVerificationUri;
static String statusTokenExpiry;

// Status (read-only, updated in loop)
static String statusWiFi;
static String statusSignal;
static String statusIP;
static String statusUptime;
static String statusSDStatus;
static String statusSDFree;
static String statusRecording;
static String statusUploadQueue;
static String statusFlushDrops;
static float dashRingFill = 0;

// WiFi reconnection interval
#define WIFI_RECONNECT_INTERVAL_MS (15 * 60 * 1000)

// Dashboard push interval (5 seconds)
#define DASHBOARD_PUSH_INTERVAL_MS (5 * 1000)

// ── Dashboard setup ───────────────────────────────────────────────

static void setupDashboard() {
    // Load saved settings into String variables
    cfgHostname = deviceSettings.hostname;
    cfgServerHost = deviceSettings.serverHost;
    cfgServerPort = String(deviceSettings.serverPort);
    cfgDevicePw = deviceSettings.devicePassword;
    cfgOAuthIssuer = deviceSettings.oauthIssuer;
    cfgOAuthClientId = deviceSettings.oauthClientId;

    dash.lang("en");

    // ════════════════════════════════════════════════════════════════
    // Settings Tab
    // ════════════════════════════════════════════════════════════════
    dash.tab("Settings");

    dash.separator("Network");
    dash.text("Hostname (.local)", &cfgHostname, [](const String& v) {
        strlcpy(deviceSettings.hostname, v.c_str(), sizeof(deviceSettings.hostname));
    });
    dash.text("Server Host", &cfgServerHost, [](const String& v) {
        strlcpy(deviceSettings.serverHost, v.c_str(), sizeof(deviceSettings.serverHost));
    });
    dash.text("Server Port", &cfgServerPort, [](const String& v) {
        deviceSettings.serverPort = atoi(v.c_str());
    });
    dash.password("Device Password", &cfgDevicePw, [](const String& v) {
        strlcpy(deviceSettings.devicePassword, v.c_str(), sizeof(deviceSettings.devicePassword));
    });

    dash.separator("OAuth2");
    dash.text("Issuer URL", &cfgOAuthIssuer, [](const String& v) {
        strlcpy(deviceSettings.oauthIssuer, v.c_str(), sizeof(deviceSettings.oauthIssuer));
    });
    dash.text("Client ID", &cfgOAuthClientId, [](const String& v) {
        strlcpy(deviceSettings.oauthClientId, v.c_str(), sizeof(deviceSettings.oauthClientId));
    });
    dash.button("Authorize", "Authorize", []() {
        if (deviceSettings.oauthIssuer[0] && deviceSettings.oauthClientId[0]) {
            OAuth2Config oauthCfg;
            oauthCfg.issuer = deviceSettings.oauthIssuer;
            oauthCfg.clientId = deviceSettings.oauthClientId;
            oauthCfg.scope = deviceSettings.oauthScope;
            oauthCfg.timeoutMs = 600000;
            oauth2Client().configure(oauthCfg);
            oauth2Client().start();
            // Persist to "device" namespace so reboot doesn't overwrite with stale values
            Preferences p;
            p.begin("device", false);
            p.putString("oauth_issuer", deviceSettings.oauthIssuer);
            p.putString("oauth_client_id", deviceSettings.oauthClientId);
            p.end();
            ESP_LOGI("OAUTH", "Device code flow started");
        }
    });
    dash.button("Clear Auth", "Clear", []() {
        oauth2Client().clearTokens();
        // Clear from "device" namespace so reboot doesn't restore stale issuer/client ID
        Preferences p;
        p.begin("device", false);
        p.remove("oauth_issuer");
        p.remove("oauth_client_id");
        p.end();
        ESP_LOGI("OAUTH", "Tokens cleared");
    });

    dash.button("Save & Restart", "Save", []() {
        saveDeviceSettings();
        delay(500);
        ESP.restart();
    });
    dash.button("Reconfigure WiFi", "Reconfigure", []() {
        dash.forgetWiFi();
    });

    // ════════════════════════════════════════════════════════════════
    // Status Tab
    // ════════════════════════════════════════════════════════════════
    dash.tab("Status");

    // ── WiFi ──
    dash.separator("WiFi");
    dash.label("Network", &statusWiFi);
    dash.label("Signal", &statusSignal);
    dash.label("IP Address", &statusIP);

    // ── Device ──
    dash.separator("Device");
    dash.label("Uptime", &statusUptime);
    dash.label("SD Status", &statusSDStatus);
    dash.label("SD Free", &statusSDFree);

    // ── Auth ──
    dash.separator("Auth");
    dash.label("Auth State", &statusAuthState);
    dash.label("User Code", &statusUserCode);
    dash.label("Verification URL", &statusVerificationUri);
    dash.label("Token Expiry", &statusTokenExpiry);

    // ── Audio ──
    dash.separator("Audio");
    dash.label("Recording", &statusRecording);
    dash.label("Upload Queue", &statusUploadQueue);
    dash.label("Flush Drops", &statusFlushDrops);
    dash.chart("Ring Fill", &dashRingFill, "/32");
}

// ── OTA routes (registered AFTER dash.begin() so they override RisalDash's defaults) ──

static void setupOTA() {
    dash.server().on("/update", AsyncWebRequestMethod::HTTP_GET, [](AsyncWebServerRequest* r) {
        r->send(200, "text/html",
                "<!DOCTYPE html><meta name=viewport content=\"width=device-width,initial-scale=1\">"
                "<body style=\"font-family:sans-serif;background:#0F1115;color:#F2F4F8;padding:32px\">"
                "<h2>OTA update</h2><form method=POST action=/update enctype=multipart/form-data>"
                "<input type=file name=firmware> <button>Upload</button></form></body>");
    });
    dash.server().on(
        "/update", AsyncWebRequestMethod::HTTP_POST,
        [](AsyncWebServerRequest* r) {
            bool ok = !Update.hasError();
            ESP_LOGI("OTA", "result: %s", ok ? "success" : "FAILED");
            if (ok) {
                const esp_partition_t* next = esp_ota_get_next_update_partition(NULL);
                if (next) {
                    ESP_LOGI("OTA", "setting boot partition to %s", next->label);
                    esp_ota_set_boot_partition(next);
                }
            }
            r->send(200, "text/plain", ok ? "OK, rebooting" : "update failed");
            if (ok) {
                // Defer reboot so the event loop can flush the response
                static esp_timer_handle_t otaRebootTimer;
                static esp_timer_create_args_t otaRebootArgs = {
                    .callback = [](void*) { ESP.restart(); },
                    .name = "ota_reboot"
                };
                esp_timer_create(&otaRebootArgs, &otaRebootTimer);
                esp_timer_start_once(otaRebootTimer, 500000); // 500ms
            }
        },
        [](AsyncWebServerRequest*, String, size_t index, uint8_t* data, size_t len, bool final) {
            static bool otaInProgress = false;
            static uint32_t totalWritten = 0;
            if (index == 0) {
                // Stop audio tasks — they contend with flash erase
                if (feedTaskHandle) vTaskSuspend(feedTaskHandle);
                if (fetchTaskHandle) vTaskSuspend(fetchTaskHandle);
                if (writerTaskHandle) vTaskSuspend(writerTaskHandle);
                ESP_LOGI("OTA", "audio tasks suspended");
                // Remove idle from WDT — flash erase blocks Core 0 for seconds
                esp_task_wdt_delete(xTaskGetHandle("idle"));
                otaInProgress = Update.begin(UPDATE_SIZE_UNKNOWN);
                totalWritten = 0;
                ESP_LOGI("OTA", "start: begin=%d", otaInProgress);
                if (!otaInProgress) ESP_LOGE("OTA", "begin FAILED: %d", Update.getError());
            }
            if (otaInProgress && len) {
                size_t written = Update.write(data, len);
                totalWritten += written;
                if (written != len) ESP_LOGE("OTA", "write mismatch: %d != %d", written, len);
            }
            if (final) {
                ESP_LOGI("OTA", "end: total=%lu, result=%d", totalWritten, Update.end(true));
                if (Update.hasError()) ESP_LOGE("OTA", "end FAILED: %d", Update.getError());
            }
        });
    ESP_LOGI("OTA", "custom handler registered");
}

// ── Dashboard status updater ───────────────────────────────────────
// Reads cached stats from audio workers; dash.update() pushes to browser.

static void updateDashboardStatus() {
    // WiFi
    statusWiFi = WiFi.SSID();
    statusSignal = String(WiFi.RSSI()) + " dBm";
    statusIP = WiFi.localIP().toString();

    // Uptime
    unsigned long sec = millis() / 1000;
    statusUptime = String(sec / 3600) + "h " + String((sec % 3600) / 60) + "m " + String(sec % 60) + "s";

    // SD card (direct register reads — no mutex, <1ms)
    if (SD.cardType() != CARD_NONE) {
        statusSDStatus = "OK";
        uint64_t total = SD.totalBytes();
        uint64_t free_ = total - SD.usedBytes();
        statusSDFree = String(free_ / 1024) + " KB / " + String(total / (1024 * 1024)) + " MB";
    } else {
        statusSDStatus = "No card";
        statusSDFree = "N/A";
    }

    // OAuth2 status — only show user code/URL during active polling
    switch (oauth2Client().getState()) {
        case AUTH_IDLE:
            statusAuthState = "Not configured";
            statusUserCode = "";
            statusVerificationUri = "";
            statusTokenExpiry = "";
            break;
        case AUTH_REQUESTING_CODE:
            statusAuthState = "Requesting code...";
            statusUserCode = "";
            statusVerificationUri = "";
            statusTokenExpiry = "";
            break;
        case AUTH_DISPLAYING_CODE:
        case AUTH_POLLING:
            statusAuthState = "Waiting for authorization";
            statusUserCode = oauth2Client().getUserCode();
            statusVerificationUri = oauth2Client().getVerificationUri();
            statusTokenExpiry = "";
            break;
        case AUTHENTICATED:
            statusAuthState = "Authenticated";
            statusUserCode = "";
            statusVerificationUri = "";
            {
                uint32_t secs = oauth2Client().getTokenExpiresInSeconds();
                if (secs > 3600) {
                    statusTokenExpiry = "Expires in " + String(secs / 3600) + "h";
                } else if (secs > 60) {
                    statusTokenExpiry = "Expires in " + String(secs / 60) + "m";
                } else if (secs > 0) {
                    statusTokenExpiry = "Expires in " + String(secs) + "s";
                } else {
                    statusTokenExpiry = "Expired";
                }
            }
            break;
        case AUTH_ERROR:
            statusAuthState = String("Error: ") + oauth2Client().getLastError();
            statusUserCode = "";
            statusVerificationUri = "";
            statusTokenExpiry = "";
            break;
    }

    // Audio (direct reads — no intermediate cache needed)
    statusRecording = recording ? "Active" : "Idle";
    statusUploadQueue = String(getUploadQueueDepth());
    statusFlushDrops = String(getFlushDropCount());
    dashRingFill = (float)getRingFillLevel();
}

// ── mDNS ───────────────────────────────────────────────────────────

static void setupMDNS() {
    if (MDNS.begin(deviceSettings.hostname)) {
        ESP_LOGI("WIFI", "mDNS: http://%s.local", deviceSettings.hostname);
        MDNS.addService("http", "tcp", 80);
    } else {
        ESP_LOGW("WIFI", "mDNS failed");
    }
}

// ── SD Card ────────────────────────────────────────────────────────

static void setupSD() {
    // Initialize SD like the guide: SD.begin(21)
    if (!SD.begin(SD_CS_PIN, SPI, 25000000)) {
        ESP_LOGE("SD", "Mount failed");
        return;
    }

    uint8_t t = SD.cardType();
    if (t == CARD_NONE) {
        ESP_LOGW("SD", "No card detected");
        return;
    }

    const char* names[] = {"UNKNOWN","MMC","SD","SDHC"};
    ESP_LOGI("SD", "Mounted: %s %llu MB @ 25MHz", names[t], SD.cardSize()/(1024*1024));

    if (!SD.exists("lifelog")) {
        SD.mkdir("lifelog");
        ESP_LOGI("SD", "Created /lifelog");
    }
}

// ── Forward declarations ──────────────────────────────────────────
static void logStats();

// ── PSRAM-aware mbedtls allocator (replaces INTERNAL_MEM_ALLOC) ──
// ESP-IDF 5.x SDK bakes CONFIG_MBEDTLS_INTERNAL_MEM_ALLOC=1 into the
// precompiled library.  mbedtls_platform_set_calloc_free() lets us
// redirect allocations at runtime.  Try PSRAM first, fall back to
// internal RAM so TLS always works even if PSRAM is fragmented.
static void *psram_calloc(size_t n, size_t size) {
    size_t total = n * size;
    if (total == 0) return NULL;
    void *ptr = heap_caps_malloc(total, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!ptr) ptr = heap_caps_malloc(total, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (ptr) memset(ptr, 0, total);
    return ptr;
}
static void psram_free(void *ptr) {
    heap_caps_free(ptr);
}

// ── Main ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);

    // Redirect mbedtls to PSRAM-aware allocators — the SDK precompiled
    // library uses INTERNAL_MEM_ALLOC which exhausts internal SRAM when
    // AFE + WiFi + web server are all active.
    mbedtls_platform_set_calloc_free(psram_calloc, psram_free);

    // Runtime log levels — set early so all boot messages visible
    esp_log_level_set("*", ESP_LOG_DEBUG);
    esp_log_level_set("SD", ESP_LOG_DEBUG);
    esp_log_level_set("AFE_FEED", ESP_LOG_INFO);
    esp_log_level_set("WRITER", ESP_LOG_INFO);
    esp_log_level_set("UPLOAD", ESP_LOG_INFO);
    esp_log_level_set("WIFI", ESP_LOG_INFO);
    esp_log_level_set("ASYNC_TCP", ESP_LOG_ERROR);

#ifdef SLOW_BOOT
    delay(10000);
#endif
    delay(1000);
    ESP_LOGI("BOOT", "=== LifeLog OTA Demo ===");
    const esp_partition_t* running = esp_ota_get_running_partition();
    ESP_LOGI("BOOT", "Running partition: %s (offset=0x%06x, size=0x%06x)",
             running ? running->label : "NULL",
             running ? running->address : 0,
             running ? running->size : 0);

    esp_register_freertos_idle_hook_for_cpu(idleHook0, 0);
    esp_register_freertos_idle_hook_for_cpu(idleHook1, 1);

#ifdef BUILD_DEVELOPMENT
    taskman_setup();
#endif

    pinMode(LED_PIN, OUTPUT);
    bootInit();
    loadDeviceSettings();

    // Initialize OAuth2 config (but don't start task yet — WiFi not connected)
    oauth2ClientInit();
    if (deviceSettings.oauthIssuer[0] && deviceSettings.oauthClientId[0]) {
        OAuth2Config oauthCfg;
        oauthCfg.issuer = deviceSettings.oauthIssuer;
        oauthCfg.clientId = deviceSettings.oauthClientId;
        oauthCfg.scope = deviceSettings.oauthScope;
        oauthCfg.timeoutMs = 600000;
        oauth2Client().configure(oauthCfg);
    }

    setupSD();
    setupDashboard();

    // dash.begin() handles WiFi:
    // - First boot (no saved creds) → captive portal AP, blocks until configured
    // - Saved creds → STA mode, connects to known network
    dash.begin();
    setupOTA();  // Register AFTER dash.begin() so we override RisalDash's /update routes

#ifdef BUILD_DEVELOPMENT
    taskman_server_setup();
    ESP_LOGI("SYSTEM", "Task Manager: http://%s:81/taskman", WiFi.localIP().toString().c_str());
#endif

    // Start OAuth2 background task AFTER WiFi is connected
    if (deviceSettings.oauthIssuer[0] && deviceSettings.oauthClientId[0]) {
        oauth2Client().start();
        if (!oauth2Client().hasValidToken()) {
            ESP_LOGI("OAUTH", "Device code flow started (no valid token)");
        } else {
            ESP_LOGI("OAUTH", "Background token refresh active");
        }
    }

    setupMDNS();
    audioInit();

    updateDashboardStatus();  // Initial status before first browser connects

    // Audio tasks
    xTaskCreatePinnedToCore(afeFeedTask, "afe_feed", 8192, NULL, PRIO_AUDIO, &feedTaskHandle, 0);
    xTaskCreatePinnedToCore(afeFetchTask, "afe_fetch", 8192, NULL, PRIO_AUDIO, &fetchTaskHandle, 1);
    xTaskCreatePinnedToCore(writerTask, "writer", 49152, NULL, PRIO_AUDIO, &writerTaskHandle, 1);

    bootConfirm();

    logStats();
    loop();
}

static void logStats() {
    static uint32_t lastStatsMs = 0;
    uint32_t now = millis();
    uint32_t elapsed = now - lastStatsMs;
    if (elapsed < 60000) return;  // every 60 seconds
    lastStatsMs = now;

    // ── Per-core CPU usage via idle hook counts ──
    uint32_t c0 = idleCount0; idleCount0 = 0;
    uint32_t c1 = idleCount1; idleCount1 = 0;
    // Each idle hook invocation ≈ 1 tick. Busy% = (elapsed - idle) / elapsed * 100
    uint32_t busy0 = (elapsed > c0) ? (elapsed - c0) * 100 / elapsed : 0;
    uint32_t busy1 = (elapsed > c1) ? (elapsed - c1) * 100 / elapsed : 0;
    ESP_LOGI("SYSTEM", "cpu0: %lu%% busy, cpu1: %lu%% busy", busy0, busy1);

    // ── Task enumeration via uxTaskGetSnapshotAll ──
    UBaseType_t taskCount = uxTaskGetNumberOfTasks();
    TaskSnapshot_t *snapshots = (TaskSnapshot_t *)pvPortMalloc(taskCount * sizeof(TaskSnapshot_t));
    if (snapshots) {
        UBaseType_t tcbSize;
        UBaseType_t actual = uxTaskGetSnapshotAll(snapshots, taskCount, &tcbSize);
        ESP_LOGI("SYSTEM", "--- %lu tasks ---", (unsigned long)actual);

        for (UBaseType_t i = 0; i < actual; i++) {
            TaskHandle_t handle = (TaskHandle_t)snapshots[i].pxTCB;
            const char *name = pcTaskGetName(handle);
            eTaskState state = eTaskGetState(handle);
            const char *stateStr;
            switch (state) {
                case eRunning:   stateStr = "RUN"; break;
                case eReady:     stateStr = "READY"; break;
                case eBlocked:   stateStr = "BLOCKED"; break;
                case eSuspended: stateStr = "SUSPENDED"; break;
                case eDeleted:   stateStr = "DELETED"; break;
                default:         stateStr = "?"; break;
            }
            UBaseType_t stackFree = uxTaskGetStackHighWaterMark(handle);
            ESP_LOGI("SYSTEM", "  %-12s %5luB %s", name, (unsigned long)stackFree * 4, stateStr);
        }
        vPortFree(snapshots);
    }

    // ── Memory ──
    ESP_LOGI("SYSTEM", "heap free: %lu bytes", (unsigned long)ESP.getFreeHeap());
    ESP_LOGI("SYSTEM", "psram free: %lu bytes", (unsigned long)ESP.getFreePsram());

    // ── Buffer health ──
    ESP_LOGI("SYSTEM", "buf stalls: %lu (max %lu ms)",
               (unsigned long)getWriterStallCount(),
               (unsigned long)getWriterStallMaxMs());
    ESP_LOGI("SYSTEM", "dma partials: %lu, flush drops: %lu",
               (unsigned long)getDmaPartialCount(),
               (unsigned long)getFlushDropCount());
    ESP_LOGI("SYSTEM", "samples captured: %lu, written: %lu",
               (unsigned long)getTotalSamplesCaptured(),
               (unsigned long)getTotalSamplesWritten());
    ESP_LOGI("SYSTEM", "ring fill: %lu/32", (unsigned long)getRingFillLevel());
}

void loop() {
    // WiFi reconnection: if disconnected, try reconnecting periodically
    static uint32_t lastReconnectAttempt = 0;
    if (WiFi.status() != WL_CONNECTED && millis() - lastReconnectAttempt > WIFI_RECONNECT_INTERVAL_MS) {
        lastReconnectAttempt = millis();
        ESP_LOGI("WIFI", "WiFi disconnected — reconnecting...");
        WiFi.reconnect();
    }

    // Push widget values to browser every 5 seconds
    static uint32_t lastDashPush = 0;
    static bool chartToggle = false;
    if (millis() - lastDashPush > DASHBOARD_PUSH_INTERVAL_MS) {
        updateDashboardStatus();
        // Toggle 0.001 bit so chart always registers as "changed"
        // (RisalDash deduplicates identical values; this is invisible on a /32 scale)
        dashRingFill += chartToggle ? 0.001f : -0.001f;
        chartToggle = !chartToggle;
        lastDashPush = millis();
        dash.update();
    }
}
