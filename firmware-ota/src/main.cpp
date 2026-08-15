#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <driver/i2s.h>
#include <WiFiManager.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <esp_ota_ops.h>
#include <RemoteDebug.h>
#include <opus.h>

#define LED_PIN  21
#define MAX_BOOT 3

// SD Card - XIAO ESP32-S3 Sense built-in slot
#define SD_CS_PIN   21

// PDM Microphone - Sense built-in
#define I2S_MIC_CLK  42
#define I2S_MIC_DIN  41

// Audio
#define SAMPLE_RATE     16000
#define OPUS_BITRATE    24000
#define OPUS_FRAME_SIZE 960   // 60ms at 16kHz
#define REC_BUF_SAMPLES (SAMPLE_RATE * 30)  // 30 seconds max recording
#define VAD_THRESHOLD   500   // RMS threshold for voice detection
#define VAD_SILENCE_MS  1500  // 1.5s silence = end of utterance
#define VAD_CHUNK_MS    30    // 30ms audio chunks for VAD processing

// Opus encoder state
static OpusEncoder* opusEncoder = NULL;
static uint8_t opusBuffer[1024];
static int16_t encodeBuffer[OPUS_FRAME_SIZE];

static Preferences prefs;
static const char* NS = "ota";
static RemoteDebug Debug;
static TaskHandle_t audioTaskHandle = NULL;
static volatile bool recording = false;
static volatile bool vadMode = true;
static uint32_t fileIndex = 0;
static uint32_t recordDurationMs = 5000;

void processCommand();

#define LOG(fmt, ...) do { \
    Serial.printf(fmt "\n", ##__VA_ARGS__); \
    debugD(fmt, ##__VA_ARGS__); \
} while(0)

// ── Audio Capture ──────────────────────────────────────────────────

static float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

static void audioCaptureTask(void *pvParameters) {
    int16_t* recBuffer = (int16_t*)ps_malloc(REC_BUF_SAMPLES * 2);
    if (!recBuffer) recBuffer = (int16_t*)malloc(REC_BUF_SAMPLES * 2);
    if (!recBuffer) { LOG("[AUDIO] Buffer alloc FAILED"); return; }
    LOG("[AUDIO] PCM buffer ready (%d bytes)", REC_BUF_SAMPLES * 2);

    opusEncoder = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_RESTRICTED_LOWDELAY, NULL);
    if (!opusEncoder) { LOG("[AUDIO] Opus encoder creation failed"); return; }
    opus_encoder_ctl(opusEncoder, OPUS_SET_BITRATE(OPUS_BITRATE));
    opus_encoder_ctl(opusEncoder, OPUS_SET_COMPLEXITY(1));
    LOG("[AUDIO] Opus ready (bitrate=%d)", OPUS_BITRATE);
    LOG("[AUDIO] VAD mode: threshold=%d, silence=%dms", VAD_THRESHOLD, VAD_SILENCE_MS);

    // VAD state
    bool voiceActive = false;
    uint32_t silenceMs = 0;
    uint32_t captured = 0;
    uint32_t startMs = 0;

    while (true) {
        if (!recording) {
            voiceActive = false;
            silenceMs = 0;
            captured = 0;
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }

        // Read one chunk of audio
        int chunkSamples = VAD_CHUNK_MS * SAMPLE_RATE / 1000;  // 480 samples for 30ms
        int16_t chunkBuffer[480];
        size_t bytesRead = 0;
        esp_err_t err = i2s_read(I2S_NUM_0, chunkBuffer, chunkSamples * 2, &bytesRead, pdMS_TO_TICKS(100));

        if (err != ESP_OK || bytesRead == 0) continue;

        int samplesRead = bytesRead / 2;
        float rms = computeRMS(chunkBuffer, samplesRead);

        if (vadMode) {
            // VAD mode: detect speech start/end
            if (rms > VAD_THRESHOLD) {
                if (!voiceActive) {
                    // Voice started
                    voiceActive = true;
                    silenceMs = 0;
                    captured = 0;
                    startMs = millis();
                    LOG("[VAD] Voice started (RMS=%.0f)", rms);
                }
                silenceMs = 0;

                // Copy chunk to recording buffer
                if (captured + samplesRead <= REC_BUF_SAMPLES) {
                    memcpy(recBuffer + captured, chunkBuffer, bytesRead);
                    captured += samplesRead;
                }
            } else if (voiceActive) {
                // Silence during voice
                silenceMs += VAD_CHUNK_MS;

                // Still copy silence to buffer (keeps audio natural)
                if (captured + samplesRead <= REC_BUF_SAMPLES) {
                    memcpy(recBuffer + captured, chunkBuffer, bytesRead);
                    captured += samplesRead;
                }

                if (silenceMs >= VAD_SILENCE_MS) {
                    // End of utterance
                    voiceActive = false;
                    LOG("[VAD] Voice ended (RMS=%.0f, %d ms, %d samples)", rms, millis() - startMs, captured);

                    // Save the utterance
                    if (captured > 0) {
                        char filename[64];
                        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", fileIndex++);

                        File file = SD.open(filename, FILE_WRITE);
                        if (file) {
                            uint32_t totalEncoded = 0;
                            uint32_t pcmIndex = 0;

                            while (pcmIndex < captured) {
                                int samplesAvailable = captured - pcmIndex;
                                int samplesToEncode = (samplesAvailable < OPUS_FRAME_SIZE) ? samplesAvailable : OPUS_FRAME_SIZE;

                                memcpy(encodeBuffer, recBuffer + pcmIndex, samplesToEncode * 2);
                                if (samplesToEncode < OPUS_FRAME_SIZE) {
                                    memset(encodeBuffer + samplesToEncode, 0, (OPUS_FRAME_SIZE - samplesToEncode) * 2);
                                }

                                int bytesEncoded = opus_encode(opusEncoder, encodeBuffer, OPUS_FRAME_SIZE,
                                                               opusBuffer, sizeof(opusBuffer));

                                if (bytesEncoded > 0) {
                                    uint16_t frameLen = (uint16_t)bytesEncoded;
                                    file.write((uint8_t*)&frameLen, 2);
                                    file.write(opusBuffer, bytesEncoded);
                                    totalEncoded += bytesEncoded + 2;
                                }
                                pcmIndex += samplesToEncode;
                            }

                            file.close();
                            LOG("[VAD] Saved: %s (%d bytes opus)", filename, totalEncoded);
                        } else {
                            LOG("[VAD] Failed to open %s", filename);
                        }
                    }

                    captured = 0;
                    silenceMs = 0;
                }
            }
        } else {
            // Fixed duration mode (original behavior)
            if (captured == 0) startMs = millis();

            if (captured + samplesRead <= REC_BUF_SAMPLES) {
                memcpy(recBuffer + captured, chunkBuffer, bytesRead);
                captured += samplesRead;
            }

            uint32_t totalSamples = SAMPLE_RATE * (recordDurationMs / 1000);
            if (captured >= totalSamples) {
                LOG("[AUDIO] Captured %d samples in %d ms", captured, millis() - startMs);

                char filename[64];
                snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", fileIndex++);

                File file = SD.open(filename, FILE_WRITE);
                if (file) {
                    uint32_t totalEncoded = 0;
                    uint32_t pcmIndex = 0;

                    while (pcmIndex < captured) {
                        int samplesAvailable = captured - pcmIndex;
                        int samplesToEncode = (samplesAvailable < OPUS_FRAME_SIZE) ? samplesAvailable : OPUS_FRAME_SIZE;

                        memcpy(encodeBuffer, recBuffer + pcmIndex, samplesToEncode * 2);
                        if (samplesToEncode < OPUS_FRAME_SIZE) {
                            memset(encodeBuffer + samplesToEncode, 0, (OPUS_FRAME_SIZE - samplesToEncode) * 2);
                        }

                        int bytesEncoded = opus_encode(opusEncoder, encodeBuffer, OPUS_FRAME_SIZE,
                                                       opusBuffer, sizeof(opusBuffer));

                        if (bytesEncoded > 0) {
                            uint16_t frameLen = (uint16_t)bytesEncoded;
                            file.write((uint8_t*)&frameLen, 2);
                            file.write(opusBuffer, bytesEncoded);
                            totalEncoded += bytesEncoded + 2;
                        }
                        pcmIndex += samplesToEncode;
                    }

                    file.close();
                    LOG("[AUDIO] Saved: %s (%d bytes opus, %d bytes PCM)",
                        filename, totalEncoded, captured * 2);
                }
                recording = false;
            }
        }
    }
}

static void startRecording(uint32_t durationMs) {
    if (recording) return;
    recordDurationMs = durationMs;
    recording = true;
}

static void toggleVAD() {
    vadMode = !vadMode;
    LOG("[VAD] Mode: %s", vadMode ? "VAD (auto)" : "Fixed duration");
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
    Debug.setHelpProjectsCmds("rec - start recording\nstop - stop\nls - list files\nvad - toggle VAD mode");
}

// ── Telnet Commands ────────────────────────────────────────────────

void processCommand() {
    String cmd = Debug.getLastCommand();
    cmd.trim();
    if (cmd == "rec") {
        if (vadMode) {
            LOG("[VAD] Listening... (speak to record, silence saves)");
            recording = true;
        } else {
            startRecording(5000);
        }
    } else if (cmd == "stop") {
        recording = false;
        LOG("[AUDIO] Stopped");
    } else if (cmd == "vad") {
        toggleVAD();
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

    xTaskCreatePinnedToCore(audioCaptureTask, "audio", 32768, NULL, 2, &audioTaskHandle, 1);
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
