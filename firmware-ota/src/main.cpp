#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <RisalUI.h>
#include <WiFi.h>
#include <esp_ota_ops.h>
#include <esp_task_wdt.h>
#include <esp_freertos_hooks.h>
#include <freertos/task.h>
#include <esp_additions/freertos/task_snapshot.h>
#include <ArduinoJson.h>
#include "config.h"
#include "settings.h"
#include "audio.h"
#include "upload.h"
#include "commands.h"

#define MAX_BOOT 3
#define HOSTNAME "LifeLog"

static Preferences prefs;
static const char* NS = "ota";
static TaskHandle_t audioTaskHandle = NULL;
static TaskHandle_t writerTaskHandle = NULL;

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
        LOG_BOOT(LOG_INFO, "Firmware confirmed");
    } else {
        boots++;
        LOG_BOOT(LOG_WARN, "Boot %d/%d (unconfirmed)", boots, MAX_BOOT);
        prefs.putUChar("boots", boots);
    }
    prefs.end();
}

static void bootConfirm() {
    prefs.begin(NS, false);
    prefs.putUChar("confirmed", 1);
    prefs.putUChar("boots", 0);
    prefs.end();
    LOG_BOOT(LOG_INFO, "Firmware confirmed");
}

// ── NVS load/save ─────────────────────────────────────────────────

static void loadDeviceSettings() {
    Preferences p;
    p.begin("device", true);
    strlcpy(deviceSettings.hostname, p.getString("hostname", DEFAULT_HOSTNAME).c_str(), sizeof(deviceSettings.hostname));
    strlcpy(deviceSettings.serverHost, p.getString("server_host", DEFAULT_SERVER_HOST).c_str(), sizeof(deviceSettings.serverHost));
    deviceSettings.serverPort = p.getUShort("server_port", DEFAULT_SERVER_PORT);
    strlcpy(deviceSettings.serverPath, p.getString("server_path", DEFAULT_SERVER_PATH).c_str(), sizeof(deviceSettings.serverPath));
    strlcpy(deviceSettings.apiKey, p.getString("api_key", API_KEY).c_str(), sizeof(deviceSettings.apiKey));
    strlcpy(deviceSettings.devicePassword, p.getString("device_pw", "").c_str(), sizeof(deviceSettings.devicePassword));
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
    LOG_WIFI(LOG_INFO, "Loaded %d known networks", knownNetworkCount);
}

static void saveDeviceSettings() {
    Preferences p;
    p.begin("device", false);
    p.putString("hostname", deviceSettings.hostname);
    p.putString("server_host", deviceSettings.serverHost);
    p.putUShort("server_port", deviceSettings.serverPort);
    p.putString("server_path", deviceSettings.serverPath);
    p.putString("api_key", deviceSettings.apiKey);
    p.putString("device_pw", deviceSettings.devicePassword);
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
static String cfgServerPath;
static String cfgApiKey;
static String cfgDevicePw;

// Status (read-only, updated in loop)
static String statusWiFi;
static String statusSignal;
static String statusIP;
static String statusUptime;
static String statusSDStatus;
static String statusSDFree;
static String statusSDFiles;
static String statusRecording;
static String statusVAD;
static String statusUploadQueue;
static String statusFlushDrops;

// WiFi reconnection interval
#define WIFI_RECONNECT_INTERVAL_MS (15 * 60 * 1000)

// Dashboard update interval (5 minutes)
#define DASHBOARD_UPDATE_INTERVAL_MS (5 * 60 * 1000)

// ── Dashboard setup ───────────────────────────────────────────────

static void setupDashboard() {
    // Load saved settings into String variables
    cfgHostname = deviceSettings.hostname;
    cfgServerHost = deviceSettings.serverHost;
    cfgServerPort = String(deviceSettings.serverPort);
    cfgServerPath = deviceSettings.serverPath;
    cfgApiKey = deviceSettings.apiKey;
    cfgDevicePw = deviceSettings.devicePassword;

    // ── OTA ──
    dash.enableOTA();

    // ── Settings (editable) ──
    dash.separator("Settings");
    dash.text("Hostname (.local)", &cfgHostname, [](const String& v) {
        strlcpy(deviceSettings.hostname, v.c_str(), sizeof(deviceSettings.hostname));
    });
    dash.text("Server Host", &cfgServerHost, [](const String& v) {
        strlcpy(deviceSettings.serverHost, v.c_str(), sizeof(deviceSettings.serverHost));
    });
    dash.text("Server Port", &cfgServerPort, [](const String& v) {
        deviceSettings.serverPort = atoi(v.c_str());
    });
    dash.text("Server Path", &cfgServerPath, [](const String& v) {
        strlcpy(deviceSettings.serverPath, v.c_str(), sizeof(deviceSettings.serverPath));
    });
    dash.text("API Key", &cfgApiKey, [](const String& v) {
        strlcpy(deviceSettings.apiKey, v.c_str(), sizeof(deviceSettings.apiKey));
    });
    dash.text("Device Password", &cfgDevicePw, [](const String& v) {
        strlcpy(deviceSettings.devicePassword, v.c_str(), sizeof(deviceSettings.devicePassword));
    });
    dash.button("Save & Restart", "Save", []() {
        saveDeviceSettings();
        delay(500);
        ESP.restart();
    });
    dash.button("Reconfigure WiFi", "Reconfigure", []() {
        dash.forgetWiFi();
    });

    // ── WiFi Status ──
    dash.separator("WiFi");
    dash.label("Network", &statusWiFi);
    dash.label("Signal", &statusSignal);
    dash.label("IP Address", &statusIP);

    // ── Device Status ──
    dash.separator("Device Status");
    dash.label("Uptime", &statusUptime);

    // ── SD Card ──
    dash.separator("SD Card");
    dash.label("Status", &statusSDStatus);
    dash.label("Free Space", &statusSDFree);
    dash.label("Files in /lifelog", &statusSDFiles);

    // ── Audio ──
    dash.separator("Audio");
    dash.label("Recording", &statusRecording);
    dash.label("VAD Mode", &statusVAD);
    dash.label("Upload Queue", &statusUploadQueue);
    dash.label("Flush Drops", &statusFlushDrops);
}

// ── Dashboard status updater ───────────────────────────────────────
// Reads cached stats from audio workers; dash.update() pushes to browser.

static void updateDashboardStatus() {
    const auto& stats = getDashboardStats();

    // WiFi
    statusWiFi = WiFi.SSID();
    statusSignal = String(WiFi.RSSI()) + " dBm";
    statusIP = WiFi.localIP().toString();

    // Uptime
    unsigned long sec = millis() / 1000;
    statusUptime = String(sec / 3600) + "h " + String((sec % 3600) / 60) + "m " + String(sec % 60) + "s";

    // SD card (from cached stats)
    if (stats.sdTotalBytes > 0) {
        statusSDStatus = "OK";
        statusSDFree = String(stats.sdFreeBytes / 1024) + " KB / " + String(stats.sdTotalBytes / (1024 * 1024)) + " MB";
        statusSDFiles = String(stats.sdFileCount);
    } else {
        statusSDStatus = "No card";
        statusSDFree = "N/A";
        statusSDFiles = "N/A";
    }

    // Audio (from cached stats)
    statusRecording = stats.recording ? "Active" : "Idle";
    statusVAD = stats.vadMode ? "On" : "Off";
    statusUploadQueue = String(stats.uploadQueueDepth);
    statusFlushDrops = String(stats.flushDrops);
}

// ── mDNS ───────────────────────────────────────────────────────────

static void setupMDNS() {
    if (MDNS.begin(deviceSettings.hostname)) {
        LOG_WIFI(LOG_INFO, "mDNS: http://%s.local", deviceSettings.hostname);
        MDNS.addService("http", "tcp", 80);
    } else {
        LOG_WIFI(LOG_WARN, "mDNS failed");
    }
}

// ── SD Card ────────────────────────────────────────────────────────

static void setupSD() {
    // Initialize SD like the guide: SD.begin(21)
    if (!SD.begin(SD_CS_PIN, SPI, 25000000)) {
        LOG_SD(LOG_ERROR, "Mount failed");
        return;
    }

    uint8_t t = SD.cardType();
    if (t == CARD_NONE) {
        LOG_SD(LOG_WARN, "No card detected");
        return;
    }

    const char* names[] = {"UNKNOWN","MMC","SD","SDHC"};
    LOG_SD(LOG_INFO, "Mounted: %s %llu MB @ 25MHz", names[t], SD.cardSize()/(1024*1024));

    if (!SD.exists("lifelog")) {
        SD.mkdir("lifelog");
        LOG_SD(LOG_INFO, "Created /lifelog");
    }
}

// ── Main ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println("\n=== LifeLog OTA Demo ===");

    esp_register_freertos_idle_hook_for_cpu(idleHook0, 0);
    esp_register_freertos_idle_hook_for_cpu(idleHook1, 1);

    pinMode(LED_PIN, OUTPUT);
    bootInit();
    loadDeviceSettings();

    setupSD();
    setupDashboard();

    // dash.begin() handles WiFi:
    // - First boot (no saved creds) → captive portal AP, blocks until configured
    // - Saved creds → STA mode, connects to known network
    dash.begin();

    setupMDNS();
    audioInit();
    updateDashboardStatus();  // Initial status before first browser connects

    // Audio tasks — Core 0: I2S feed + AFE fetch. Core 1: writer + loop.
    xTaskCreatePinnedToCore(afeFeedTask, "afe_feed", 8192, NULL, PRIO_AUDIO, NULL, 0);
    xTaskCreatePinnedToCore(afeFetchTask, "afe_fetch", 8192, NULL, PRIO_AUDIO, NULL, 0);
    xTaskCreatePinnedToCore(writerTask, "writer", 49152, NULL, 3, &writerTaskHandle, 1);
    setWriterTaskHandle(writerTaskHandle);
    esp_task_wdt_delete(NULL);
    esp_task_wdt_delete(xTaskGetHandle("idle"));

    bootConfirm();
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
    LOG_SYSTEM(LOG_INFO, "cpu0: %lu%% busy, cpu1: %lu%% busy", busy0, busy1);

    // ── Task enumeration via uxTaskGetSnapshotAll ──
    UBaseType_t taskCount = uxTaskGetNumberOfTasks();
    TaskSnapshot_t *snapshots = (TaskSnapshot_t *)pvPortMalloc(taskCount * sizeof(TaskSnapshot_t));
    if (snapshots) {
        UBaseType_t tcbSize;
        UBaseType_t actual = uxTaskGetSnapshotAll(snapshots, taskCount, &tcbSize);
        LOG_SYSTEM(LOG_INFO, "--- %lu tasks ---", (unsigned long)actual);

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
            LOG_SYSTEM(LOG_INFO, "  %-12s %5luB %s", name, (unsigned long)stackFree * 4, stateStr);
        }
        vPortFree(snapshots);
    }

    // ── Memory ──
    LOG_SYSTEM(LOG_INFO, "heap free: %lu bytes", (unsigned long)ESP.getFreeHeap());
    LOG_SYSTEM(LOG_INFO, "psram free: %lu bytes", (unsigned long)ESP.getFreePsram());

    // ── Buffer health ──
    LOG_SYSTEM(LOG_INFO, "buf stalls: %lu (max %lu ms)",
               (unsigned long)getWriterStallCount(),
               (unsigned long)getWriterStallMaxMs());
    LOG_SYSTEM(LOG_INFO, "dma partials: %lu, flush drops: %lu",
               (unsigned long)getDmaPartialCount(),
               (unsigned long)getFlushDropCount());
    LOG_SYSTEM(LOG_INFO, "samples captured: %lu, written: %lu",
               (unsigned long)getTotalSamplesCaptured(),
               (unsigned long)getTotalSamplesWritten());
}

void loop() {
    LOG_SYSTEM(LOG_INFO, "Running Loop...");

    // WiFi reconnection: if disconnected, try reconnecting periodically
    static uint32_t lastReconnectAttempt = 0;
    if (WiFi.status() != WL_CONNECTED && millis() - lastReconnectAttempt > WIFI_RECONNECT_INTERVAL_MS) {
        lastReconnectAttempt = millis();
        LOG_WIFI(LOG_INFO, "WiFi disconnected — reconnecting...");
        WiFi.reconnect();
    }

    // Update dashboard status every 5 minutes
    static uint32_t lastDashboardUpdate = 0;
    if (millis() - lastDashboardUpdate > DASHBOARD_UPDATE_INTERVAL_MS) {
        lastDashboardUpdate = millis();
        updateDashboardStatus();
    }

    dash.update();  // Pushes changed widget values to browser via WebSocket
    logStats();
}
