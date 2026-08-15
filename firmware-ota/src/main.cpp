#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <driver/i2s.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <esp_ota_ops.h>
#include <RemoteDebug.h>

#define LED_PIN  21
#define MAX_BOOT 3

// SD Card - XIAO ESP32-S3 Sense built-in slot
#define SD_CS_PIN   21

// PDM Microphone - Sense built-in
#define I2S_MIC_CLK  42
#define I2S_MIC_DIN  41

// Audio
#define SAMPLE_RATE     16000
#define REC_BUF_SAMPLES (SAMPLE_RATE * 5)  // 5 seconds

static Preferences prefs;
static const char* NS = "ota";
static RemoteDebug Debug;
static TaskHandle_t audioTaskHandle = NULL;
static volatile bool recording = false;
static uint32_t fileIndex = 0;
static uint32_t recordDurationMs = 5000;

void processCommand();

#define LOG(fmt, ...) do { \
    Serial.printf(fmt "\n", ##__VA_ARGS__); \
    debugD(fmt, ##__VA_ARGS__); \
} while(0)

// ── Audio Capture ──────────────────────────────────────────────────

static void audioCaptureTask(void *pvParameters) {
    int16_t* recBuffer = (int16_t*)ps_malloc(REC_BUF_SAMPLES * 2);
    if (!recBuffer) recBuffer = (int16_t*)malloc(REC_BUF_SAMPLES * 2);
    if (!recBuffer) { LOG("[AUDIO] Buffer alloc FAILED"); return; }
    LOG("[AUDIO] Buffer ready (%d bytes)", REC_BUF_SAMPLES * 2);

    while (true) {
        if (!recording) { vTaskDelay(pdMS_TO_TICKS(100)); continue; }

        uint32_t totalSamples = SAMPLE_RATE * (recordDurationMs / 1000);
        uint32_t captured = 0;
        uint32_t startMs = millis();
        LOG("[AUDIO] Recording %d seconds...", recordDurationMs / 1000);

        while (recording && captured < totalSamples) {
            size_t bytesRead = 0;
            int bytesNeeded = (totalSamples - captured) * 2;
            if (bytesNeeded > 960) bytesNeeded = 960;
            i2s_read(I2S_NUM_0, recBuffer + captured, bytesNeeded, &bytesRead, pdMS_TO_TICKS(100));
            if (bytesRead > 0) captured += bytesRead / 2;
        }

        LOG("[AUDIO] Captured %d samples in %d ms", captured, millis() - startMs);

        // Write WAV to SD
        char filename[64];
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);
        File file = SD.open(filename, FILE_WRITE);
        if (file) {
            uint32_t dataSize = captured * 2;
            uint32_t fileSize = 36 + dataSize;
            uint32_t byteRate = SAMPLE_RATE * 2;
            uint16_t audioFmt = 1, numCh = 1, bits = 16, blockAlign = 2, fmtSize = 16;
            file.write((uint8_t*)"RIFF", 4);
            file.write((uint8_t*)&fileSize, 4);
            file.write((uint8_t*)"WAVE", 4);
            file.write((uint8_t*)"fmt ", 4);
            file.write((uint8_t*)&fmtSize, 4);
            file.write((uint8_t*)&audioFmt, 2);
            file.write((uint8_t*)&numCh, 2);
            uint32_t sampleRate = SAMPLE_RATE;
            file.write((uint8_t*)&sampleRate, 4);
            file.write((uint8_t*)&byteRate, 4);
            file.write((uint8_t*)&blockAlign, 2);
            file.write((uint8_t*)&bits, 2);
            file.write((uint8_t*)"data", 4);
            file.write((uint8_t*)&dataSize, 4);
            file.write((uint8_t*)recBuffer, dataSize);
            file.close();
            LOG("[AUDIO] Saved: %s (%d bytes)", filename, fileSize + 8);
        } else {
            LOG("[AUDIO] Failed to open %s", filename);
        }
        recording = false;
    }
}

static void startRecording(uint32_t durationMs) {
    if (recording) return;
    recordDurationMs = durationMs;
    recording = true;
}

// ── PDM Microphone ────────────────────────────────────────────────

static void setupMic() {
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = 480,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0
    };
    i2s_pin_config_t pin_config = {
        .bck_io_num = I2S_PIN_NO_CHANGE,
        .ws_io_num = I2S_MIC_CLK,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = I2S_MIC_DIN
    };
    if (i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL) != ESP_OK) {
        LOG("[I2S] Driver install failed"); return;
    }
    if (i2s_set_pin(I2S_NUM_0, &pin_config) != ESP_OK) {
        LOG("[I2S] Pin config failed"); return;
    }
    LOG("[I2S] PDM Mic ready (CLK=%d, DIN=%d)", I2S_MIC_CLK, I2S_MIC_DIN);
}

// ── SD Card ────────────────────────────────────────────────────────

static void setupSD() {
    if (!SD.begin(SD_CS_PIN)) { LOG("[SD] Mount failed"); return; }
    uint8_t t = SD.cardType();
    if (t == CARD_NONE) { LOG("[SD] No card"); return; }
    const char* names[] = {"UNKNOWN","MMC","SD","SDHC"};
    LOG("[SD] Mounted: %s %llu MB", names[t], SD.cardSize()/(1024*1024));
    if (!SD.exists("/lifelog")) { SD.mkdir("/lifelog"); LOG("[SD] Created /lifelog"); }
}

// ── Boot tracking ──────────────────────────────────────────────────

static void bootInit() {
    prefs.begin(NS, false);
    bool confirmed = prefs.getUChar("confirmed", 0);
    uint8_t boots = prefs.getUChar("boots", 0);
    if (confirmed) {
        LOG("[BOOT] Firmware confirmed");
    } else {
        boots++;
        LOG("[BOOT] Boot %d/%d (unconfirmed)", boots, MAX_BOOT);
        prefs.putUChar("boots", boots);
    }
    prefs.end();
}

static void bootConfirm() {
    prefs.begin(NS, false);
    prefs.putUChar("confirmed", 1);
    prefs.putUChar("boots", 0);
    prefs.end();
    LOG("[BOOT] Firmware confirmed");
}

// ── WiFi ───────────────────────────────────────────────────────────

static void setupWiFi() {
    WiFiManager wm;
    wm.setConfigPortalTimeout(120);
    wm.setConnectTimeout(10);
    if (!wm.autoConnect("LifeLog-Setup")) {
        LOG("[WIFI] Config portal timed out");
    } else {
        LOG("[WIFI] Connected: %s", WiFi.localIP().toString().c_str());
    }
}

// ── OTA ────────────────────────────────────────────────────────────

static void setupOTA() {
    ArduinoOTA.setHostname("lifelog");
    ArduinoOTA.onStart([]() {
        LOG("[OTA] Start");
        prefs.begin(NS, false);
        prefs.putUChar("confirmed", 0);
        prefs.putUChar("boots", 0);
        prefs.end();
    });
    ArduinoOTA.onEnd([]() { LOG("[OTA] Done. Rebooting..."); });
    ArduinoOTA.onProgress([](unsigned int p, unsigned int t) {
        LOG("[OTA] %u%%", (p / (t / 100)));
    });
    ArduinoOTA.onError([](ota_error_t e) { LOG("[OTA] Error %d", e); });
    ArduinoOTA.begin();
    LOG("[OTA] ArduinoOTA ready");
}

// ── Debug ──────────────────────────────────────────────────────────

static void setupDebug() {
    Debug.begin("lifelog", RemoteDebug::VERBOSE);
    Debug.setSerialEnabled(true);
    Debug.setCallBackProjectCmds(processCommand);
    Debug.setHelpProjectsCmds("rec - start recording\nstop - stop\nls - list files");
}

// ── Telnet Commands ────────────────────────────────────────────────

void processCommand() {
    String cmd = Debug.getLastCommand();
    cmd.trim();
    if (cmd == "rec") {
        startRecording(5000);
    } else if (cmd == "stop") {
        recording = false;
        LOG("[AUDIO] Stopped");
    } else if (cmd == "ls") {
        File root = SD.open("/lifelog");
        if (root) {
            File f = root.openNextFile();
            while (f) { LOG("[LS] %s %d bytes", f.name(), f.size()); f = root.openNextFile(); }
            root.close();
        }
    } else {
        LOG("[CMD] Unknown: %s", cmd.c_str());
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
    setupDebug();
    setupSD();
    setupMic();
    setupOTA();

    xTaskCreatePinnedToCore(audioCaptureTask, "audio", 8192, NULL, 2, &audioTaskHandle, 1);
    LOG("[RTOS] Audio capture task created");

    bootConfirm();
    LOG("[SYSTEM] Ready! Commands: rec, stop, ls");
}

void loop() {
    ArduinoOTA.handle();
    Debug.handle();
    digitalWrite(LED_PIN, HIGH);
    delay(1000);
    digitalWrite(LED_PIN, LOW);
    delay(1000);
}
