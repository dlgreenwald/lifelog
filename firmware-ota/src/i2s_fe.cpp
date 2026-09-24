// I2S driver + AFE init + feed/fetch tasks
// Moved from audio.cpp for TAG granularity (TAG = "AFE").

#include "i2s_fe.h"
#include "audio.h"
#include "config.h"
#include "driver/i2s_pdm.h"
#include "driver/i2s_common.h"
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

// ── I2S channel handle (new API) ─────────────────────────────────
static i2s_chan_handle_t i2s_rx_chan = NULL;

// ── AFE globals ──────────────────────────────────────────────────
static const esp_afe_sr_iface_t *afe_handle = NULL;
static esp_afe_sr_data_t *afe_data = NULL;

// ── Lightweight fixed-point AGC ─────────────────────────────────────
// Measures RMS per 512-sample frame, applies adaptive gain to normalise
// level.  Integer-only arithmetic — no FPU needed, safe for the feed task
// on ESP32 Xtensa without hardware FPU.
//
// Target: ~0.25 (= -12 dBFS) RMS for comfortable speech level.
// Max boost: ×32 (+30 dB).  Max cut: ÷4 (-12 dB).
// Gain changes are smoothed to avoid discontinuities.

typedef struct {
    int32_t rms_q19;      // Q19.13 EMA of RMS × 8192 (avoids float)
    int32_t gain_q16;     // Q16.16 current gain multiplier
} AgcState;

static AgcState agcState = {0};

// Target RMS × 8192  (2000 ≈ -24 dBFS for 16-bit PCM — comfortable distant-speech level)
#define AGC_TARGET_RMS    2000
// Min gain × 65536   (0.25 = -12 dB max attenuation)
#define AGC_MIN_GAIN      16384
// Max gain × 65536   (56.2 = +45 dB max boost — covers quiet speakers at -122 dBFS noise floor)
#define AGC_MAX_GAIN      11653503
// EMA coefficient for RMS tracking  (α=0.1, Q19.13)
#define AGC_RMS_ALPHA_Q13 3277
// EMA coefficient for gain smoothing (α=0.05, Q16.16)
#define AGC_GAIN_ALPHA_Q16 3277

static void agcReset(AgcState *s) {
    if (!s) return;
    // Seed rms_q19=200 → first agcProcessFrame computes target_gain ≈ 20 dB.
    // AGC then converges up or down naturally from there based on signal level.
    s->rms_q19 = 200;  // was AGC_TARGET_RMS (2000=0 dB); start at 20 dB instead
    s->gain_q16 = 65536;  // unity gain
}

static int agcInit(AgcState *s) {
    if (!s) return -1;
    s->rms_q19 = 200;  // start at 20 dB (see agcReset for rationale)
    s->gain_q16 = 65536;
    return 0;
}

// Multiply two Q16.16 numbers → Q16.16 result
static inline int32_t mul_q16(int32_t a, int32_t b) {
    // a and b are Q16.16; result is Q16.16
    // Use 64-bit intermediate to avoid overflow: max is 2^31 × 2^31
    return (int32_t)((((int64_t)a * b) + 32768) >> 16);
}

// Apply gain to a 512-sample frame in-place
//gain_q16 is Q16.16, returns updated gain
static int32_t agcProcessFrame(AgcState *s, int16_t *samples, int count) {
    if (!s || !samples || count <= 0) return -1;

    // VAD cache path: partial frames pass through unchanged
    if (count != 512) return 0;

    // ── 1. Compute frame RMS (Q19.13) ──────────────────────────────
    int64_t sum_sq = 0;
    for (int i = 0; i < count; i++) {
        int32_t x = samples[i];
        sum_sq += (int64_t)x * x;
    }
    // mean_sq Q19.13: divide by 512, then ×8192 (= << 4 then /512 = >> 9)
    int32_t mean_sq_q19 = (int32_t)(sum_sq >> 9);
    // Fast integer sqrt: binary-search approximation (worst case ~16 iterations)
    int32_t rms_q19 = 0;
    if (mean_sq_q19 > 0) {
        int32_t hi = 1 << 16;   // upper bound
        int32_t lo = 0;
        while (lo + 1 < hi) {
            int32_t mid = (lo + hi) >> 1;
            int64_t mid_sq = (int64_t)mid * mid;
            if (mid_sq <= mean_sq_q19) {
                lo = mid;
            } else {
                hi = mid;
            }
        }
        rms_q19 = lo;
    }

    // ── 2. Update RMS EMA ─────────────────────────────────────────
    // ema_new = ema_old + α × (sample - ema_old)
    int32_t diff = rms_q19 - s->rms_q19;
    s->rms_q19 += (int32_t)(((int64_t)AGC_RMS_ALPHA_Q13 * diff + 4096) >> 13);

    // ── 3. Compute target gain ───────────────────────────────────
    int32_t rms = s->rms_q19 > 0 ? s->rms_q19 : 1;
    // target_gain_Q16 = AGC_TARGET_RMS / rms × 65536
    int64_t target_gain = ((int64_t)AGC_TARGET_RMS * 65536) / rms;
    if (target_gain < AGC_MIN_GAIN) target_gain = AGC_MIN_GAIN;
    if (target_gain > AGC_MAX_GAIN) target_gain = AGC_MAX_GAIN;

    // ── 4. Smooth gain ──────────────────────────────────────────
    int32_t gain_diff = (int32_t)target_gain - s->gain_q16;
    s->gain_q16 += (int32_t)(((int64_t)AGC_GAIN_ALPHA_Q16 * gain_diff + 32768) >> 16);

    // ── 5. Apply gain to all 512 samples ────────────────────────
    int32_t g = s->gain_q16;
    for (int i = 0; i < count; i++) {
        int32_t x = samples[i];
        int64_t y = ((int64_t)x * g + 32768) >> 16;
        if (y > 32767) y = 32767;
        else if (y < -32768) y = -32768;
        samples[i] = (int16_t)y;
    }

    return 0;
}

// ── I2S PDM init ──────────────────────────────────────────────────

static void pdmRxInit() {
    // ESP-IDF 5.x new I2S PDM RX API
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 6;
    chan_cfg.dma_frame_num = 240;

    esp_err_t err = i2s_new_channel(&chan_cfg, NULL, &i2s_rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel failed: %d", err);
        return;
    }

    i2s_pdm_rx_config_t pdm_rx_cfg = {
        .clk_cfg  = I2S_PDM_RX_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_PDM_RX_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .clk = (gpio_num_t)I2S_MIC_CLK,  // PDM CLK = GPIO42
            .din = (gpio_num_t)I2S_MIC_DIN,  // PDM DIN = GPIO41
            .invert_flags = { .clk_inv = false },
        },
    };

    err = i2s_channel_init_pdm_rx_mode(i2s_rx_chan, &pdm_rx_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_init_pdm_rx_mode failed: %d", err);
        return;
    }

    err = i2s_channel_enable(i2s_rx_chan);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_enable failed: %d", err);
        return;
    }

    ESP_LOGD(TAG, "PDM Mic ready (CLK=42, DIN=41) — new I2S PDM RX API");
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
    afe_config_t *afe_config = afe_config_init("M", models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (!afe_config) {
        ESP_LOGE(TAG, "afe_config_init failed");
        return;
    }
    // We only need VAD + AGC — disable wake word and AEC
    afe_config->wakenet_init = false;
    afe_config->aec_init = false;

    // Enable Noise Suprression as VADNet expects it
    afe_config->ns_init = true;   // put nsnet2 in front of VADNet

    // --- VAD (VADNet) ---
    afe_config->vad_init = true;              // default is true [^c13304#34-38]
    afe_config->vad_mode = VAD_MODE_3;        // higher mode = more trigger-happy
    afe_config->vad_min_speech_ms = 128;      // min continuous speech before VAD triggers
    afe_config->vad_min_noise_ms = 1000;      // min silence before VAD declares end of speech
    afe_config->vad_delay_ms = 128;

    afe_config->agc_init = false;
    afe_config->agc_compression_gain_db = 12;  // max boost AGC can apply to quiet signals (esp-sr default 9)
    afe_config->agc_target_level_dbfs = 3;    // target -3 dBFS envelope (industry standard for speech)
    afe_config->afe_linear_gain = 1.0;         // no manual boost — AGC controls gain adaptively

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

    // Lightweight fixed-point AGC — 512-sample AFE frames, 16 kHz
    if (agcInit(&agcState) != 0) {
        ESP_LOGW(TAG, "AGC init failed — AGC disabled");
    } else {
        ESP_LOGI(TAG, "AGC ready (target=-24 dBFS, range 42 dB)");
    }
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
        i2s_channel_read(i2s_rx_chan, buf, chunksize * nch * sizeof(int16_t), &bytesRead, 100);
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

    static uint32_t rawStartMs = 0;
    uint32_t elapsed = millis() - rawStartMs;

    /* --- energy logging (temp debug) --- */
    if (result != NULL && result->data != NULL && result->data_size > 0) {
        size_t n_samples = result->data_size / sizeof(int16_t);
        const int16_t *samples = (const int16_t *)result->data;

        float sum_sq = 0.0f;
        for (size_t i = 0; i < n_samples; i++) {
            float s = (float)samples[i];
            sum_sq += s * s;
        }
        float rms = sqrtf(sum_sq / (float)n_samples);
        float dbfs = 20.0f * log10f(rms / 32768.0f);

        static int log_count = 0;
        if ((log_count++ % 50) == 0) {
            ESP_LOGD("ENERGY", "t=%lus rms=%.0f dbfs=%.1f (floor -60.0) state=%d cache=%d n=%u",
                     (unsigned long)(elapsed / 1000), rms, dbfs,
                     result->vad_state, result->vad_cache_size,
                     (unsigned)n_samples);
        }
    }
    /* --- end debug insert --- */
    
    /* --- normal VAD-driven logic (unchanged below) --- */
    static bool wasVoice = false;
    bool isVoice = (result->vad_state == VAD_SPEECH);

    if (isVoice && !wasVoice) {
        ESP_LOGD(TAG, "Voice started (utterance %lu) vol=%.1f dBFS cache=%d",
                (unsigned long)utteranceId + 1, result->data_volume, result->vad_cache_size);
    } else if (!isVoice && wasVoice) {
        ESP_LOGD(TAG, "Voice ended — signaling writer to drain ring");
    }

    if (isVoice) {
        if (!wasVoice) {
            listenStartMs = millis();
            audioActivity = AUDIO_LISTEN;
            recording = true;
            utteranceId++;
            chunkIndex = 0;
            isFinal = false;
            agcReset(&agcState);  // Clear gain history at start of new utterance
        }

        // Build chunk: VAD cache (if present) + AFE audio
        int16_t chunk[RING_ITEM_BYTES / sizeof(int16_t)];  // 512 samples on stack
        int chunkSamples = 0;

        // VAD cache (pre-trigger audio — avoids truncating first word)
        // Zero-pad at the FRONT to align to 512-sample boundary so AGC can
        // process a full frame.  Padding is before the real audio so no
        // artificial silence is inserted between cache and the current frame.
        if (result->vad_cache_size > 0 && !wasVoice) {
            int cacheSamples = result->vad_cache_size / sizeof(int16_t);
            if (cacheSamples <= RING_ITEM_BYTES / (int)sizeof(int16_t)) {
                int aligned = ((cacheSamples + 511) / 512) * 512;  // round up to 512
                int16_t alignedCache[512] = {0};
                // Place real samples at the END (zeros at front = silence before speech)
                memcpy(alignedCache + (aligned - cacheSamples), result->vad_cache, result->vad_cache_size);
                agcProcessFrame(&agcState, alignedCache, aligned);
                // Copy only the real samples back (zeros excluded)
                memcpy(chunk, result->vad_cache, result->vad_cache_size);
                chunkSamples = cacheSamples;
            }
        }

        // AFE-processed audio (NS-cleaned, AGC'd)
        int samples = result->data_size / sizeof(int16_t);
        if (samples > 0) {
            agcProcessFrame(&agcState, (int16_t *)result->data, samples);
        }

        // Rate-limited AGC diagnostic — log gain + input RMS once per second during speech
        {
            static uint32_t last_agc_log_ms = 0;
            uint32_t now_ms = millis();
            if (now_ms - last_agc_log_ms >= 1000) {
                float gain_db = 20.0f * log10f((float)agcState.gain_q16 / 65536.0f);
                float rms_dbfs = 20.0f * log10f((float)agcState.rms_q19 / 8192.0f / 32768.0f);
                ESP_LOGI(TAG, "AGC gain=%.1f dB  rms=%.1f dBFS  vad=1", gain_db, rms_dbfs);
                last_agc_log_ms = now_ms;
            }
        }

        int available = (RING_ITEM_BYTES / (int)sizeof(int16_t)) - chunkSamples;
        int toCopy = (samples <= available) ? samples : available;
        memcpy(chunk + chunkSamples, result->data, toCopy * sizeof(int16_t));
        chunkSamples += toCopy;

        // Send to ring buffer (drop oldest on overflow)
        size_t chunkBytes = chunkSamples * sizeof(int16_t);
        if (xRingbufferSend(audioRingBuf, chunk, chunkBytes, pdMS_TO_TICKS(0)) != pdTRUE) {
            // Ring full — drop up to 3 oldest items to make room (handles NOSPLIT fragmentation)
            int dropped = 0;
            while (dropped < 3) {
                size_t itemSize;
                void *oldItem = xRingbufferReceive(audioRingBuf, &itemSize, 0);
                if (!oldItem) break;
                vRingbufferReturnItem(audioRingBuf, oldItem);
                dropped++;
                flushDropCount++;
                if (xRingbufferSend(audioRingBuf, chunk, chunkBytes, pdMS_TO_TICKS(0)) == pdTRUE) {
                    break;  // Made room
                }
            }
            if (dropped > 0) {
                UBaseType_t uxItemsWaiting = 0;
                vRingbufferGetInfo(audioRingBuf, NULL, NULL, NULL, NULL, &uxItemsWaiting);
                static uint32_t lastOverflowMs = 0;
                uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
                // Rate-limit: log at most once per second to avoid drowning sd flush logs
                if (now - lastOverflowMs >= 1000) {
                    ESP_LOGW(TAG, "Ring overflow: dropped %d chunks (fill=%lu/%d writer=%s) [rate-limited: 1/sec]",
                             dropped, (unsigned long)uxItemsWaiting, RING_NUM_ITEMS,
                             pcTaskGetName(writerTaskHandle));
                    lastOverflowMs = now;
                }
            }
        }

        totalSamplesCaptured += toCopy;

        // Wake writer to drain ring
        if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
    } else if (wasVoice) {
        audioActivity = AUDIO_IDLE;
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
