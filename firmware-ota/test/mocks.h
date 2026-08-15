#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>

// Mock ESP32 types
typedef int32_t esp_err_t;
typedef int32_t BaseType_t;
typedef uint32_t TickType_t;
typedef void* QueueHandle_t;
typedef void* TaskHandle_t;
typedef void* SemaphoreHandle_t;

#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_INTR_FLAG_LEVEL1 0
#define ESP_ERR_TIMEOUT -1

// Mock FreeRTOS
#define pdMS_TO_TICKS(x) ((x))
#define pdMS_TO_TICKS(x) ((x))
#define portMAX_DELAY 0xFFFFFFFF
#define pdTRUE 1
#define pdFALSE 0

// Mock I2S
#define I2S_NUM_0 0
#define I2S_MODE_MASTER 1
#define I2S_MODE_RX 2
#define I2S_MODE_PDM 4
#define I2S_BITS_PER_SAMPLE_16BIT 16
#define I2S_CHANNEL_FMT_ONLY_LEFT 1
#define I2S_COMM_FORMAT_STAND_I2S 1
#define I2S_PIN_NO_CHANGE -1

typedef struct {
    int mode;
    int sample_rate;
    int bits_per_sample;
    int channel_format;
    int communication_format;
    int intr_alloc_flags;
    int dma_buf_count;
    int dma_buf_len;
    int use_apll;
    int tx_desc_auto_clear;
    int fixed_mclk;
} i2s_config_t;

typedef struct {
    int bck_io_num;
    int ws_io_num;
    int data_out_num;
    int data_in_num;
} i2s_pin_config_t;

// Mock functions
inline esp_err_t i2s_driver_install(int i2s_num, const i2s_config_t* config, int queue_size, void* queue) { return ESP_OK; }
inline esp_err_t i2s_set_pin(int i2s_num, const i2s_pin_config_t* pin_config) { return ESP_OK; }
inline esp_err_t i2s_read(int i2s_num, void* buf, size_t size, size_t* bytes_read, TickType_t timeout) {
    // Return silence (zeros)
    memset(buf, 0, size);
    *bytes_read = size;
    return ESP_OK;
}

// Mock FreeRTOS functions
inline QueueHandle_t xQueueCreate(int queue_length, int item_size) { return (QueueHandle_t)1; }
inline BaseType_t xQueueSend(QueueHandle_t queue, const void* item, TickType_t timeout) { return pdTRUE; }
inline BaseType_t xQueueReceive(QueueHandle_t queue, void* buffer, TickType_t timeout) { return pdTRUE; }
inline TaskHandle_t xTaskCreatePinnedToCore(void (*task)(void*), const char* name, uint32_t stack_size, void* params, int priority, TaskHandle_t* task_handle, int core) { return (TaskHandle_t)1; }
inline void vTaskDelay(TickType_t ticks) {}
inline void free(void* ptr) { std::free(ptr); }
