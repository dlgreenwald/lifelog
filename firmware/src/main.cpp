#include <Arduino.h>
#include <SPI.h>
#include <SD.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>
#include <freertos/event_groups.h>
#include <driver/i2s.h>
#include "config.h"
#include "audio_capture.h"
#include "opus_encoder.h"
#include "sd_storage.h"
#include "wifi_manager.h"
#include "uploader.h"
#include "battery.h"
#include "ota_manager.h"

// Task handles
TaskHandle_t audioCaptureHandle = NULL;
TaskHandle_t opusEncodeHandle = NULL;
TaskHandle_t uploaderHandle = NULL;
TaskHandle_t batteryMonitorHandle = NULL;

// Shared queues
QueueHandle_t pcmQueue = NULL;
QueueHandle_t opusQueue = NULL;
SemaphoreHandle_t sdMutex = NULL;
EventGroupHandle_t wifiEvent = NULL;

// Global state
volatile bool recording = true;

void initSDCard() {
    SPI.begin(SD_SCLK, SD_MISO, SD_MOSI, SD_CS_PIN);
    if (!SD.begin(SD_CS_PIN)) {
        Serial.println("[SD] Card mount failed");
        return;
    }
    Serial.printf("[SD] Card mounted, type: %d\n", SD.cardType());
    
    // Create lifelog directory if not exists
    if (!SD.exists("/lifelog")) {
        SD.mkdir("/lifelog");
        Serial.println("[SD] Created /lifelog directory");
    }
}

void initI2SMic() {
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 8,
        .dma_buf_len = PCM_BUFFER_SIZE,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0
    };
    
    i2s_pin_config_t pin_config = {
        .bck_io_num = I2S_MIC_SCK,
        .ws_io_num = I2S_MIC_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = I2S_MIC_SD
    };
    
    esp_err_t err = i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
    if (err != ESP_OK) {
        Serial.printf("[I2S] Driver install failed: %d\n", err);
        return;
    }
    err = i2s_set_pin(I2S_NUM_0, &pin_config);
    if (err != ESP_OK) {
        Serial.printf("[I2S] Pin config failed: %d\n", err);
        return;
    }
    Serial.printf("[I2S] Mic initialized (rate=%d, buf=%d)\n", SAMPLE_RATE, PCM_BUFFER_SIZE);
}

void initBatteryADC() {
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);
    Serial.println("[BATT] ADC initialized");
}

void initLED() {
    pinMode(LED_BLUE_PIN, OUTPUT);
    digitalWrite(LED_BLUE_PIN, LOW);
    Serial.println("[LED] Initialized");
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println("\n=== LifeLog Firmware Starting ===");

    // Initialize OTA manager (check boot state)
    otaManagerInit();

    // Init hardware
    initSDCard();
    initI2SMic();
    initBatteryADC();
    initLED();
    
    // Create queues
    pcmQueue = xQueueCreate(10, sizeof(AudioChunk));
    opusQueue = xQueueCreate(5, sizeof(OpusFrame));
    sdMutex = xSemaphoreCreateMutex();
    wifiEvent = xEventGroupCreate();
    
    if (!pcmQueue || !opusQueue || !sdMutex || !wifiEvent) {
        Serial.println("[FATAL] Queue/semaphore creation failed");
        return;
    }
    
    Serial.println("[RTOS] Queues created");
    
    // Create tasks (core pinning for dual-core ESP32-S3)
    xTaskCreatePinnedToCore(audioCaptureTask, "audio", 4096, NULL, 5, &audioCaptureHandle, 0);
    xTaskCreatePinnedToCore(opusEncodeTask, "opus", 32768, NULL, 4, &opusEncodeHandle, 1);
    xTaskCreatePinnedToCore(uploaderTask, "upload", 4096, NULL, 2, &uploaderHandle, 0);
    xTaskCreatePinnedToCore(batteryMonitorTask, "batt", 4096, NULL, 1, &batteryMonitorHandle, 0);
    
    Serial.println("[RTOS] Tasks created");

    // Start OTA server for firmware updates
    otaServerStart();

    // Mark firmware as confirmed (successful boot)
    otaConfirmFirmware();

    Serial.println("=== LifeLog Ready ===\n");
}

void loop() {
    // Handle OTA server requests
    otaServerHandleClient();
    vTaskDelay(pdMS_TO_TICKS(10));
}
