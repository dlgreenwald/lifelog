#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <esp_ota_ops.h>
#include "config.h"
#include "audio.h"
#include "upload.h"
#include "commands.h"

#define MAX_BOOT 3

static Preferences prefs;
static const char* NS = "ota";
static TaskHandle_t audioTaskHandle = NULL;

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
    if (!SD.begin(SD_CS_PIN)) {
        LOG_SD(LOG_ERROR, "Mount failed");
        return;
    }
    
    uint8_t t = SD.cardType();
    if (t == CARD_NONE) {
        LOG_SD(LOG_WARN, "No card detected");
        return;
    }
    
    const char* names[] = {"UNKNOWN","MMC","SD","SDHC"};
    LOG_SD(LOG_INFO, "Mounted: %s %llu MB", names[t], SD.cardSize()/(1024*1024));
    
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

    pinMode(LED_PIN, OUTPUT);
    bootInit();
    setupWiFi();
    setupSD();
    audioInit();
    setupOTA();
    commandsInit();

    xTaskCreatePinnedToCore(audioTask, "audio", 32768, NULL, 5, &audioTaskHandle, 1);
    xTaskCreatePinnedToCore(writerTask, "writer", 32768, NULL, 2, NULL, 0);
    bootConfirm();

    LOG_SYSTEM(LOG_INFO, "Ready! VAD active — listening for speech...");
}

void loop() {
    ArduinoOTA.handle();

    if (recording) {
        digitalWrite(LED_PIN, HIGH);
        delay(200);
        digitalWrite(LED_PIN, LOW);
        delay(200);
    } else {
        digitalWrite(LED_PIN, HIGH);
        delay(1000);
        digitalWrite(LED_PIN, LOW);
        delay(1000);
    }
}
