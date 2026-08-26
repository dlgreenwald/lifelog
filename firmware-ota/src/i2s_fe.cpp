// I2S driver + AFE init + feed/fetch tasks
// Moved from audio.cpp for TAG granularity (TAG = "AFE").

#include "i2s_fe.h"
#include "audio.h"
#include "config.h"
#include "driver/i2s.h"
#include "esp_log.h"

// esp-sr AFE includes
#include "esp_partition.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_config.h"
#include "esp_afe_sr_models.h"
#include "model_path.h"
#include "afe_stubs.h"

static const char* TAG = "AFE_FEED";

// ── Buffer health counters ────────────────────────────────────────
static uint32_t dmaPartialCount = 0;
uint32_t getDmaPartialCount() { return dmaPartialCount; }

// ── AFE globals ──────────────────────────────────────────────────
static const esp_afe_sr_iface_t *afe_handle = NULL;
static esp_afe_sr_data_t *afe_data = NULL;

// ── I2S PDM init ──────────────────────────────────────────────────

static void pdmRxInit() {
    // Direct I2S driver — PDM CLK maps to bck_io_num, DIN to data_in_num
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
        .sample_rate = SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = 1024,  // ESP-IDF max; 4 × 1024 = 4096 samples = 256ms ring buffer
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0,
        .mclk_multiple = I2S_MCLK_MULTIPLE_DEFAULT,
        .bits_per_chan = I2S_BITS_PER_CHAN_DEFAULT,
    };
    i2s_pin_config_t pin_config = {
        .mck_io_num = I2S_PIN_NO_CHANGE,
        .bck_io_num = I2S_PIN_NO_CHANGE,
        .ws_io_num = I2S_MIC_CLK,    // PDM CLK = GPIO42
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = I2S_MIC_DIN,  // PDM DIN = GPIO41
    };
    esp_err_t err = i2s_driver_install(I2S_NUM_0, &i2s_config, 0, NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_driver_install failed: %d", err);
        return;
    }
    err = i2s_set_pin(I2S_NUM_0, &pin_config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_set_pin failed: %d", err);
        return;
    }
    i2s_set_clk(I2S_NUM_0, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
    ESP_LOGD(TAG, "PDM Mic ready (CLK=42, DIN=41) — DMA: 4 × 1024 samples");
}

// ── AFE init — load models, configure AFE_TYPE_VC ──────────────────

static void afeInit() {
    const esp_partition_t *part = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "model");
    if (!part) {
        ESP_LOGE(TAG, "No 'model' partition found — AFE disabled");
        return;
    }
    uint8_t buf[4] = {0};
    esp_err_t err = esp_partition_read(part, 0, buf, sizeof(buf));
    if (err != ESP_OK || (buf[0] == 0xFF && buf[1] == 0xFF && buf[2] == 0xFF && buf[3] == 0xFF)) {
        ESP_LOGE(TAG, "Model partition empty — AFE disabled");
        return;
    }

    srmodel_list_t *models = esp_srmodel_init("model");
    if (!models) {
        ESP_LOGE(TAG, "esp_srmodel_init failed");
        return;
    }
    // Use official defaults — let afe_config_init set everything
    afe_config_t *afe_config = afe_config_init("M", models, AFE_TYPE_VC, AFE_MODE_LOW_COST);
    if (!afe_config) {
        ESP_LOGE(TAG, "afe_config_init failed");
        return;
    }
    // We only need VAD + AGC — disable wake word and AEC
    afe_config->wakenet_init = false;
    afe_config->aec_init = false;

    // Switch to WebRTC VAD (simpler, more reliable than VADNet)
    // Setting vad_model_name to NULL triggers WebRTC fallback
    if (afe_config->vad_model_name) {
        free(afe_config->vad_model_name);
        afe_config->vad_model_name = NULL;
    }

    // Enable AGC — default is off, audio too faint without it
    afe_config->agc_init = false;
    afe_config->agc_compression_gain_db = 6;   // compression gain (lower = less noise amplification)
    afe_config->agc_target_level_dbfs = 3;     // target -3 dBFS envelope
    afe_config->afe_linear_gain = 3.0;         // output multiplier (default 1.0)

    afe_handle = esp_afe_handle_from_config(afe_config);
    if (!afe_handle) {
        ESP_LOGE(TAG, "esp_afe_handle_from_config failed");
        afe_config_free(afe_config);
        return;
    }
    afe_data = afe_handle->create_from_config(afe_config);
    afe_config_free(afe_config);
    if (!afe_data) {
        ESP_LOGE(TAG, "AFE create_from_config failed");
        return;
    }

    ESP_LOGD(TAG, "AFE ready (official defaults)");
    afe_handle->print_pipeline(afe_data);
}

// ── Public init ───────────────────────────────────────────────────

void i2sFeInit() {
    pdmRxInit();
    afeInit();
}

// ── AFE feed task — reads I2S, feeds AFE (Core 0) ─────────────────

void afeFeedTask(void *pvParameters) {
    if (!afe_handle || !afe_data) {
        ESP_LOGE(TAG, "Feed task: AFE not initialized, deleting");
        vTaskDelete(NULL);
        return;
    }
    int chunksize = afe_handle->get_feed_chunksize(afe_data);
    int nch = afe_handle->get_feed_channel_num(afe_data);
    int16_t *buf = (int16_t *)heap_caps_malloc(
        chunksize * nch * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    assert(buf);
    ESP_LOGD(TAG, "Feed task started (chunksize=%d, nch=%d)", chunksize, nch);

    while (true) {
        size_t bytesRead = 0;
        i2s_read(I2S_NUM_0, buf, chunksize * nch * sizeof(int16_t), &bytesRead, pdMS_TO_TICKS(100));
        if (bytesRead > 0) {
            int samplesRead = bytesRead / sizeof(int16_t);
            if (samplesRead < chunksize * nch) {
                dmaPartialCount++;
            }
            // Feed raw audio to AFE — VADNet is trained on un-amplified levels
            afe_handle->feed(afe_data, buf);
        }

    }
}

// ── Flush helper — signal writer to drain ring buffer ──────────────

static void flushBuffer() {
    if (writerTaskHandle) {
        xTaskNotifyGive(writerTaskHandle);
    }
}

// ── AFE fetch result handler ──────────────────────────────────────

static void processAfeResult(afe_fetch_result_t *result) {
    static bool wasVoice = false;
    bool isVoice = (result->vad_state == VAD_SPEECH);

    if (isVoice && !wasVoice) {
        ESP_LOGD(TAG, "Voice started (utterance %lu) vol=%.1f dBFS cache=%d",
                (unsigned long)utteranceId + 1, result->data_volume, result->vad_cache_size);
    } else if (!isVoice && wasVoice) {
        ESP_LOGI(TAG, "Voice ended — signaling writer to drain ring");
    }

    if (isVoice) {
        if (!wasVoice) {
            recording = true;
            utteranceId++;
            chunkIndex = 0;
            isFinal = false;
        }

        // Build chunk: VAD cache (if present) + AFE audio
        int16_t chunk[RING_ITEM_BYTES / sizeof(int16_t)];  // 512 samples on stack
        int chunkSamples = 0;

        // VAD cache (pre-trigger audio — avoids truncating first word)
        if (result->vad_cache_size > 0 && !wasVoice) {
            int cacheSamples = result->vad_cache_size / sizeof(int16_t);
            if (cacheSamples <= RING_ITEM_BYTES / (int)sizeof(int16_t)) {
                memcpy(chunk, result->vad_cache, result->vad_cache_size);
                chunkSamples = cacheSamples;
            }
        }

        // AFE-processed audio (NS-cleaned)
        int samples = result->data_size / sizeof(int16_t);
        int available = (RING_ITEM_BYTES / (int)sizeof(int16_t)) - chunkSamples;
        int toCopy = (samples <= available) ? samples : available;
        memcpy(chunk + chunkSamples, result->data, toCopy * sizeof(int16_t));
        chunkSamples += toCopy;

        // Send to ring buffer (drop oldest on overflow)
        size_t chunkBytes = chunkSamples * sizeof(int16_t);
        if (xRingbufferSend(audioRingBuf, chunk, chunkBytes, pdMS_TO_TICKS(0)) != pdTRUE) {
            // Ring full — remove oldest item to make room
            size_t itemSize;
            void *oldItem = xRingbufferReceive(audioRingBuf, &itemSize, 0);
            if (oldItem != NULL) {
                vRingbufferReturnItem(audioRingBuf, oldItem);
                flushDropCount++;
                ESP_LOGW(TAG, "Ring overflow: dropped oldest chunk");
            }
            // Retry send
            xRingbufferSend(audioRingBuf, chunk, chunkBytes, pdMS_TO_TICKS(0));
        }

        totalSamplesCaptured += toCopy;

        // Wake writer to drain ring
        if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
    } else if (wasVoice) {
        recording = false;
        isFinal = true;
        flushBuffer();
    }
    wasVoice = isVoice;
}

// ── AFE fetch task — fetches processed audio + VAD (Core 1) ───────

void afeFetchTask(void *pvParameters) {
    if (!afe_handle || !afe_data) {
        ESP_LOGE(TAG, "Fetch task: AFE not initialized, deleting");
        vTaskDelete(NULL);
        return;
    }
    ESP_LOGD(TAG, "Fetch task started");

    while (true) {
        afe_fetch_result_t *result = afe_handle->fetch(afe_data);
        if (!result || result->ret_value == ESP_FAIL) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        processAfeResult(result);
    }
}
