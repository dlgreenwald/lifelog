#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <ESPUI.h>
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

// ── WiFi ───────────────────────────────────────────────────────────

#define CAPTIVE_PORTAL_STACK 8192
#define RECONNECT_SCAN_INTERVAL_MS (15 * 60 * 1000)  // 15 minutes
#define OTA_STACK 4096

// Task priorities (higher = more important)
#define PRIO_OTA            7
#define PRIO_AUDIO          5
#define PRIO_CAPTIVE        4
#define PRIO_LOOP           2
#define PRIO_BACKGROUND     1

static volatile bool wifiConnected = false;
static TaskHandle_t captivePortalTaskHandle = NULL;

static void onWiFiEvent(arduino_event_id_t event) {
    if (event == ARDUINO_EVENT_WIFI_STA_CONNECTED) { wifiConnected = true; }
    else if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) { wifiConnected = false; }
}

static bool tryConnectNetwork(const char* ssid, const char* password, uint32_t timeoutMs) {
    LOG_WIFI(LOG_INFO, "Trying network: %s", ssid);
    WiFi.disconnect();
    delay(100);
    if (password[0]) { WiFi.begin(ssid, password); }
    else { WiFi.begin(ssid); }
    uint32_t start = millis();
    while (millis() - start < timeoutMs) {
        if (WiFi.status() == WL_CONNECTED) {
            LOG_WIFI(LOG_INFO, "Connected to %s: %s (RSSI %d dBm)",
                     ssid, WiFi.localIP().toString().c_str(), WiFi.RSSI());
            return true;
        }
        delay(100);
    }
    WiFi.disconnect();
    return false;
}

// WiFiManager params and save callback
static void saveParamsCallback() {
    // Read from the WiFiManager params that were added to the portal
    // WiFiManager populates the param values when the user submits the form
    // We read them back via a separate mechanism — the portal params are
    // set up in captivePortalTask with current values, and saveParamsCallback
    // is called after the portal form is submitted.
    //
    // Note: WiFiManager.getWiFiSSID()/getWiFiPass() return the WiFi credentials
    // from the portal form, not the custom params. The custom params are read
    // via param.getValue() which WiFiManager calls the save callback after
    // populating. Since we can't access the local params from here, we rely
    // on the fact that captivePortalTask reads them after saveParamsCallback.
    LOG_WIFI(LOG_INFO, "WiFiManager params saved");
}

static void captivePortalTask(void* pvParameters) {
    LOG_WIFI(LOG_INFO, "Starting captive portal (non-blocking)");
    WiFiManager wm;
    wm.setConfigPortalTimeout(0);
    wm.setTitle("LifeLog Setup");
    wm.setSaveParamsCallback(saveParamsCallback);

    // Add custom parameters
    WiFiManagerParameter h("hostname", "Device hostname (.local)", deviceSettings.hostname, 32);
    WiFiManagerParameter sh("server_host", "Server host", deviceSettings.serverHost, 64);
    String portStr = String(deviceSettings.serverPort);
    WiFiManagerParameter sp("server_port", "Server port", portStr.c_str(), 6);
    WiFiManagerParameter sp2("server_path", "Server path", deviceSettings.serverPath, 64);
    WiFiManagerParameter ak("api_key", "API key", deviceSettings.apiKey, 128);
    WiFiManagerParameter dp("device_pw", "Device password", deviceSettings.devicePassword, 64);
    wm.addParameter(&h); wm.addParameter(&sh); wm.addParameter(&sp);
    wm.addParameter(&sp2); wm.addParameter(&ak); wm.addParameter(&dp);

    // Set AP password if configured
    const char* apPw = deviceSettings.devicePassword[0] ? deviceSettings.devicePassword : nullptr;
    wm.startConfigPortal("LifeLog-Setup", apPw);  // Blocks in this task — audio continues on other cores

    // Portal closed — read back the params
    strlcpy(deviceSettings.hostname, h.getValue(), sizeof(deviceSettings.hostname));
    strlcpy(deviceSettings.serverHost, sh.getValue(), sizeof(deviceSettings.serverHost));
    deviceSettings.serverPort = atoi(sp.getValue());
    strlcpy(deviceSettings.serverPath, sp2.getValue(), sizeof(deviceSettings.serverPath));
    strlcpy(deviceSettings.apiKey, ak.getValue(), sizeof(deviceSettings.apiKey));
    strlcpy(deviceSettings.devicePassword, dp.getValue(), sizeof(deviceSettings.devicePassword));

    // Add WiFi network from portal to known list
    String newSSID = wm.getWiFiSSID();
    String newPass = wm.getWiFiPass();
    if (newSSID.length() > 0) {
        addKnownNetwork(newSSID.c_str(), newPass.c_str());
    }
    saveDeviceSettings();
    LOG_WIFI(LOG_INFO, "Settings saved: hostname=%s server=%s:%d networks=%d",
             deviceSettings.hostname, deviceSettings.serverHost, deviceSettings.serverPort, knownNetworkCount);

    LOG_WIFI(LOG_WARN, "Captive portal ended, restarting...");
    delay(1000);
    ESP.restart();
    vTaskDelete(NULL);
}

static void setupWiFi() {
    WiFi.onEvent(onWiFiEvent);

    // Check reconfig flag
    Preferences p;
    p.begin("device", true);
    bool reconfig = p.getBool("reconfig", false);
    p.end();
    if (reconfig) {
        Preferences pw;
        pw.begin("device", false);
        pw.putBool("reconfig", false);
        pw.end();
        LOG_WIFI(LOG_INFO, "Reconfiguration mode — starting captive portal");
        xTaskCreatePinnedToCore(captivePortalTask, "captive", CAPTIVE_PORTAL_STACK, NULL, PRIO_CAPTIVE, &captivePortalTaskHandle, 1);
        return;
    }

    // Try each known network
    for (int i = 0; i < knownNetworkCount; i++) {
        if (tryConnectNetwork(knownNetworks[i].ssid, knownNetworks[i].password, WIFI_CONNECT_TIMEOUT_MS)) {
            return;  // Connected
        }
    }

    // No network available — start captive portal in background
    LOG_WIFI(LOG_WARN, "No known network in range, starting captive portal");
    xTaskCreatePinnedToCore(captivePortalTask, "captive", CAPTIVE_PORTAL_STACK, NULL, PRIO_CAPTIVE, &captivePortalTaskHandle, 1);
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

// ── OTA ────────────────────────────────────────────────────────────

static void setupOTA() {
    ArduinoOTA.setHostname(deviceSettings.hostname);
    ArduinoOTA.onStart([]() {
        LOG_OTA(LOG_INFO, "Start");
        prefs.begin(NS, false);
        prefs.putUChar("confirmed", 0);
        prefs.putUChar("boots", 0);
        prefs.end();
    });
    ArduinoOTA.onEnd([]() { LOG_OTA(LOG_INFO, "Done. Rebooting..."); });
    ArduinoOTA.onProgress([](unsigned int p, unsigned int t) {
        LOG_OTA(LOG_DEBUG, "%u%%", (p / (t / 100)));
    });
    ArduinoOTA.onError([](ota_error_t e) { LOG_OTA(LOG_ERROR, "Error %d", e); });
    ArduinoOTA.begin();
    LOG_OTA(LOG_INFO, "ArduinoOTA ready");
}

// ── OTA task (Core 1, priority 7 — highest) ───────────────────────

static void otaTask(void* pvParameters) {
    for (;;) {
        ArduinoOTA.handle();
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

// ── Auto-reconnect task (Core 1, priority 1) ──────────────────────

static void autoReconnectTask(void* pvParameters) {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(RECONNECT_SCAN_INTERVAL_MS));
        if (WiFi.status() == WL_CONNECTED) continue;
        LOG_WIFI(LOG_INFO, "Auto-reconnect: scanning for known networks...");
        for (int i = 0; i < knownNetworkCount; i++) {
            if (tryConnectNetwork(knownNetworks[i].ssid, knownNetworks[i].password, WIFI_CONNECT_TIMEOUT_MS)) {
                LOG_WIFI(LOG_INFO, "Auto-reconnect: connected to %s", knownNetworks[i].ssid);
                delay(2000);  // Let captive portal notice the disconnect
                ESP.restart();
                return;
            }
        }
    }
}

// ── ESPUI status page ──────────────────────────────────────────────

static uint16_t inpHostname, inpServerHost, inpServerPort, inpServerPath, inpApiKey, inpDevicePw;
static uint16_t btnSave, btnReconfig;
static uint16_t lblIP, lblWiFi, lblSignal, lblUptime;
static uint16_t lblSDStatus, lblSDFree, lblSDFiles;
static uint16_t lblRecording, lblVAD, lblUploadQueue, lblFlushDrops;

static void saveSettingsCallback(Control* sender, int type) {
    strlcpy(deviceSettings.hostname, ESPUI.getControl(inpHostname)->value.c_str(), sizeof(deviceSettings.hostname));
    strlcpy(deviceSettings.serverHost, ESPUI.getControl(inpServerHost)->value.c_str(), sizeof(deviceSettings.serverHost));
    deviceSettings.serverPort = atoi(ESPUI.getControl(inpServerPort)->value.c_str());
    strlcpy(deviceSettings.serverPath, ESPUI.getControl(inpServerPath)->value.c_str(), sizeof(deviceSettings.serverPath));
    strlcpy(deviceSettings.apiKey, ESPUI.getControl(inpApiKey)->value.c_str(), sizeof(deviceSettings.apiKey));
    strlcpy(deviceSettings.devicePassword, ESPUI.getControl(inpDevicePw)->value.c_str(), sizeof(deviceSettings.devicePassword));
    saveDeviceSettings();
    delay(500);
    ESP.restart();
}

static void reconfigWifiCallback(Control* sender, int type) {
    Preferences p;
    p.begin("device", false);
    p.putBool("reconfig", true);
    p.end();
    delay(500);
    ESP.restart();
}

static void setupStatusPage() {
    ESPUI.setVerbosity(Verbosity::Quiet);
    if (deviceSettings.devicePassword[0]) {
        ESPUI.begin(deviceSettings.hostname, "admin", deviceSettings.devicePassword);
    } else {
        ESPUI.begin(deviceSettings.hostname);
    }

    ESPUI.separator("Settings");
    inpHostname = ESPUI.text("Hostname (.local)", NULL, ControlColor::Dark, deviceSettings.hostname);
    inpServerHost = ESPUI.text("Server Host", NULL, ControlColor::Dark, deviceSettings.serverHost);
    inpServerPort = ESPUI.text("Server Port", NULL, ControlColor::Dark, String(deviceSettings.serverPort));
    inpServerPath = ESPUI.text("Server Path", NULL, ControlColor::Dark, deviceSettings.serverPath);
    inpApiKey = ESPUI.text("API Key", NULL, ControlColor::Dark, deviceSettings.apiKey);
    inpDevicePw = ESPUI.text("Device Password (blank = no auth)", NULL, ControlColor::Dark, deviceSettings.devicePassword);
    btnSave = ESPUI.button("Save & Restart", saveSettingsCallback, ControlColor::None, "Save");
    btnReconfig = ESPUI.button("Reconfigure WiFi", reconfigWifiCallback, ControlColor::None, "Reconfigure");

    ESPUI.separator("Device Status");
    lblIP = ESPUI.label("IP Address", ControlColor::Dark, WiFi.localIP().toString());
    lblWiFi = ESPUI.label("WiFi Network", ControlColor::Dark, WiFi.SSID());
    lblSignal = ESPUI.label("Signal", ControlColor::Dark, String(WiFi.RSSI()) + " dBm");
    lblUptime = ESPUI.label("Uptime", ControlColor::Dark, "0h 0m");

    ESPUI.separator("SD Card");
    lblSDStatus = ESPUI.label("Status", ControlColor::Dark, "Checking...");
    lblSDFree = ESPUI.label("Free Space", ControlColor::Dark, "...");
    lblSDFiles = ESPUI.label("Files in /lifelog", ControlColor::Dark, "...");

    ESPUI.separator("Audio");
    lblRecording = ESPUI.label("Recording", ControlColor::Dark, "Idle");
    lblVAD = ESPUI.label("VAD Mode", ControlColor::Dark, "Off");
    lblUploadQueue = ESPUI.label("Upload Queue", ControlColor::Dark, "0");
    lblFlushDrops = ESPUI.label("Flush Drops", ControlColor::Dark, "0");
}

static void updateStatusPage() {
    static uint32_t lastUpdate = 0;
    if (millis() - lastUpdate < 5000) return;
    lastUpdate = millis();

    unsigned long sec = millis() / 1000;
    ESPUI.updateLabel(lblUptime, String(sec/3600) + "h " + String((sec%3600)/60) + "m " + String(sec%60) + "s");
    ESPUI.updateLabel(lblSignal, String(WiFi.RSSI()) + " dBm");

    if (SD.cardType() != CARD_NONE) {
        uint64_t freeBytes = SD.totalBytes() - SD.usedBytes();
        ESPUI.updateLabel(lblSDStatus, "OK");
        ESPUI.updateLabel(lblSDFree, String(freeBytes/1024) + " KB / " + String(SD.totalBytes()/(1024*1024)) + " MB");
        int fileCount = 0;
        File root = SD.open("/lifelog");
        if (root && root.isDirectory()) {
            File f = root.openNextFile();
            while (f) { fileCount++; f = root.openNextFile(); }
            root.close();
        }
        ESPUI.updateLabel(lblSDFiles, String(fileCount));
    } else {
        ESPUI.updateLabel(lblSDStatus, "No card");
        ESPUI.updateLabel(lblSDFree, "N/A");
        ESPUI.updateLabel(lblSDFiles, "N/A");
    }

    ESPUI.updateLabel(lblRecording, recording ? "Active" : "Idle");
    ESPUI.updateLabel(lblVAD, vadMode ? "On" : "Off");
    ESPUI.updateLabel(lblUploadQueue, String(getUploadQueueDepth()));
    ESPUI.updateLabel(lblFlushDrops, String(getFlushDropCount()));
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

    bool isFirstBoot = (knownNetworkCount == 0 && deviceSettings.devicePassword[0] == '\0');

    setupWiFi();

    if (isFirstBoot) {
        // Initial Setup Mode — only SD for config storage, NO audio capture
        setupSD();
        LOG_SYSTEM(LOG_INFO, "Initial setup — connect to LifeLog-Setup AP to configure device");
    } else {
        // Run Mode — full functionality
        setupSD();
        audioInit();

        // Start OTA task (runs in both WiFi-connected and captive portal modes)
        setupOTA();
        xTaskCreatePinnedToCore(otaTask, "ota", OTA_STACK, NULL, PRIO_OTA, NULL, 1);

        if (WiFi.status() == WL_CONNECTED) {
            setupMDNS();
            commandsInit();
            setupStatusPage();
        } else {
            // Captive portal running — start auto-reconnect scanner
            xTaskCreatePinnedToCore(autoReconnectTask, "reconnect", 4096, NULL, PRIO_BACKGROUND, NULL, 1);
        }

        // Audio tasks — Core 0 gets I2S only, Core 1 gets processing
        xTaskCreatePinnedToCore(afeFeedTask, "afe_feed", 8192, NULL, PRIO_AUDIO, NULL, 0);
        xTaskCreatePinnedToCore(afeFetchTask, "afe_fetch", 8192, NULL, PRIO_AUDIO, &audioTaskHandle, 1);
        xTaskCreatePinnedToCore(writerTask, "writer", 49152, NULL, PRIO_AUDIO, &writerTaskHandle, 1);
        setWriterTaskHandle(writerTaskHandle);
        esp_task_wdt_delete(NULL);
        esp_task_wdt_delete(xTaskGetHandle("idle"));
    }

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
    // loop() runs at low priority (2) — ESPUI stats update, log stats.
    // OTA is handled by dedicated otaTask at priority 7.
    // Audio tasks at priority 5 always preempt this.
    if (WiFi.status() == WL_CONNECTED) {
        updateStatusPage();
    }
    logStats();
}
