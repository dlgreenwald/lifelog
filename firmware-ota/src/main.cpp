#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <esp_ota_ops.h>
#include <esp_task_wdt.h>
#include <esp_freertos_hooks.h>
#include <freertos/task.h>
#include <esp_additions/freertos/task_snapshot.h>
#include "config.h"
#include "audio.h"
#include "upload.h"
#include "commands.h"

#define MAX_BOOT 3

static Preferences prefs;
static const char* NS = "ota";
static TaskHandle_t audioTaskHandle = NULL;
static TaskHandle_t writerTaskHandle = NULL;

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

// ── WiFi ───────────────────────────────────────────────────────────

static void setupWiFi() {
    WiFiManager wm;
    wm.setConfigPortalTimeout(120);
    wm.setConnectTimeout(10);
    if (!wm.autoConnect("LifeLog-Setup")) {
        LOG_WIFI(LOG_WARN, "Config portal timed out");
    } else {
        LOG_WIFI(LOG_INFO, "Connected: %s", WiFi.localIP().toString().c_str());
    }
}

// ── OTA ────────────────────────────────────────────────────────────

static void setupOTA() {
    ArduinoOTA.setHostname("lifelog");
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
    setupWiFi();
    setupSD();
    audioInit();
    setupOTA();
    commandsInit();

    xTaskCreatePinnedToCore(afeFeedTask, "afe_feed", 8192, NULL, 5, NULL, 0);
    xTaskCreatePinnedToCore(afeFetchTask, "afe_fetch", 8192, NULL, 5, &audioTaskHandle, 1);
    xTaskCreatePinnedToCore(writerTask, "writer", 49152, NULL, 5, &writerTaskHandle, 1);
    setWriterTaskHandle(writerTaskHandle);

    // Disable task watchdog for idle task only — AFE tasks now use
    // i2s_read timeouts (100ms) so they yield often enough for the WDT.
    esp_task_wdt_delete(NULL);
    esp_task_wdt_delete(xTaskGetHandle("idle"));

    bootConfirm();

    LOG_SYSTEM(LOG_INFO, "Ready! AFE active (VAD + NSNET2) — listening for speech...");
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
    ArduinoOTA.handle();
    logStats();
}
