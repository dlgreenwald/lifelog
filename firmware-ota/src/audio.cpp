#include "audio.h"
#include "config.h"
#include "upload.h"
#include "driver/i2s.h"
#include <WiFi.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"

// esp-sr AFE includes
#include "esp_partition.h"
#include "esp_afe_sr_iface.h"
#include "esp_afe_config.h"
#include "esp_afe_sr_models.h"
#include "model_path.h"
#include "afe_stubs.h"

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
#include <opus.h>
#include <ogg/ogg.h>
#endif

#include "lifelog_core/codec.h"

// Global state
volatile bool recording = false;
volatile bool vadMode = true;
SemaphoreHandle_t sdMutex = NULL;
uint32_t fileIndex = 0;
uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};
static TaskHandle_t writerTaskHandle = NULL;
static QueueHandle_t uploadQueue = NULL;
static TaskHandle_t uploadTaskHandle = NULL;

// Utterance tracking
volatile uint32_t utteranceId = 0;
volatile uint32_t chunkIndex = 0;
volatile bool isFinal = false;

// ── Buffer health counters ────────────────────────────────────────
static uint32_t writerStallCount = 0;   // Times audioTask waited for writer
static uint32_t writerStallMaxMs = 0;   // Longest stall duration
static uint32_t dmaPartialCount = 0;    // i2s_read returned < requested
static uint32_t flushDropCount = 0;     // End-of-recording buffer discarded
static uint32_t totalSamplesCaptured = 0; // Total I2S samples read
static uint32_t totalSamplesWritten = 0;  // Total samples written to SD
static volatile uint32_t ringFillLevel = 0;  // Current chunks in ring (sampled by writer)

uint32_t getWriterStallCount() { return writerStallCount; }
uint32_t getWriterStallMaxMs() { return writerStallMaxMs; }
uint32_t getDmaPartialCount() { return dmaPartialCount; }
uint32_t getFlushDropCount() { return flushDropCount; }
uint32_t getTotalSamplesCaptured() { return totalSamplesCaptured; }
uint32_t getTotalSamplesWritten() { return totalSamplesWritten; }
uint32_t getRingFillLevel() { return ringFillLevel; }

// ── WAV header — delegated to lib/lifelog_core/codec.h ─────────────

// ── Forward declarations ──────────────────────────────────────────
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
static void opus_init();
static void opus_init_stream();
static int opus_encode_to_buffer(const int16_t* pcm, int samples);
static void opus_file_end();
#endif
static void upload_if_connected(const char* filename);
static void closePendingFile();
static void uploadWorkerTask(void *pvParameters);

// ── Upload request (metadata captured at file-close time) ──────────

struct UploadRequest {
    char filename[64];
    uint32_t utteranceId;
    uint32_t chunkIndex;
    bool isFinal;
};

// ── Upload helper ──────────────────────────────────────────────────

static void upload_if_connected(const UploadRequest &req) {
    if (WiFi.status() == WL_CONNECTED) {
        delay(100);
        LOG_AUDIO(LOG_INFO, "Uploading %s (utt=%lu chunk=%lu)...",
                  req.filename, (unsigned long)req.utteranceId, (unsigned long)req.chunkIndex);
        if (uploadFile(req.filename, req.utteranceId, req.chunkIndex, req.isFinal)) {
            sdTake();
            SD.remove(req.filename);
            sdGive();
            LOG_AUDIO(LOG_INFO, "Uploaded and deleted %s", req.filename);
        } else {
            LOG_AUDIO(LOG_WARN, "Upload failed: %s", req.filename);
        }
    }
    // Close deferred file after upload attempt (success or fail)
    closePendingFile();
}

// ── Public API ─────────────────────────────────────────────────────

void sdTake() {
    xSemaphoreTakeRecursive(sdMutex, portMAX_DELAY);
}

void sdGive() {
    xSemaphoreGiveRecursive(sdMutex);
}

uint32_t getUploadQueueDepth() {
    return uploadQueue ? uxQueueMessagesWaiting(uploadQueue) : 0;
}

// ── AFE globals ──────────────────────────────────────────────────

static const esp_afe_sr_iface_t *afe_handle = NULL;
static esp_afe_sr_data_t *afe_data = NULL;

// ── Legacy I2S PDM init ──────────────────────────────────────────

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
        LOG_I2S(LOG_ERROR, "i2s_driver_install failed: %d", err);
        return;
    }
    err = i2s_set_pin(I2S_NUM_0, &pin_config);
    if (err != ESP_OK) {
        LOG_I2S(LOG_ERROR, "i2s_set_pin failed: %d", err);
        return;
    }
    i2s_set_clk(I2S_NUM_0, SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
    LOG_I2S(LOG_INFO, "PDM Mic ready (CLK=42, DIN=41) — DMA: 4 × 1024 samples");
}

// ── AFE init — load models, configure AFE_TYPE_VC ──────────────────

static void afeInit() {
    const esp_partition_t *part = esp_partition_find_first(
        ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "model");
    if (!part) {
        LOG_AFE(LOG_ERROR, "No 'model' partition found — AFE disabled");
        return;
    }
    uint8_t buf[4] = {0};
    esp_err_t err = esp_partition_read(part, 0, buf, sizeof(buf));
    if (err != ESP_OK || (buf[0] == 0xFF && buf[1] == 0xFF && buf[2] == 0xFF && buf[3] == 0xFF)) {
        LOG_AFE(LOG_ERROR, "Model partition empty — AFE disabled");
        return;
    }

    srmodel_list_t *models = esp_srmodel_init("model");
    if (!models) {
        LOG_AFE(LOG_ERROR, "esp_srmodel_init failed");
        return;
    }
    // Use official defaults — let afe_config_init set everything
    afe_config_t *afe_config = afe_config_init("M", models, AFE_TYPE_VC, AFE_MODE_LOW_COST);
    if (!afe_config) {
        LOG_AFE(LOG_ERROR, "afe_config_init failed");
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
        LOG_AFE(LOG_ERROR, "esp_afe_handle_from_config failed");
        afe_config_free(afe_config);
        return;
    }
    afe_data = afe_handle->create_from_config(afe_config);
    afe_config_free(afe_config);
    if (!afe_data) {
        LOG_AFE(LOG_ERROR, "AFE create_from_config failed");
        return;
    }

    LOG_AFE(LOG_INFO, "AFE ready (official defaults)");
    afe_handle->print_pipeline(afe_data);
}

// ── Ring Buffer State ───────────────────────────────────────────────
// Producer: afeFetchTask (processAfeResult) — writes ring_head
// Consumer: writerTask — reads ring_tail
// Each slot holds one AFE chunk (~32ms at 16kHz)

#define RING_CHUNK_SAMPLES 512   // AFE feed chunksize (must divide RING_CAPACITY)
#define RING_SLOTS       32     // number of chunks buffered
#define RING_CAPACITY    (RING_SLOTS * RING_CHUNK_SAMPLES)  // total samples in ring
#define OGG_BUF_CAPACITY 16384  // 16KB PSRAM buffer for accumulated OGG pages before SD open

static int16_t *ring_buf = NULL;               // contiguous ring in PSRAM
static volatile uint32_t ring_head = 0;        // write offset in samples
static volatile uint32_t ring_tail = 0;        // read offset in samples
static SemaphoreHandle_t ring_mutex = NULL;

// ── Opus encoder state (used when AUDIO_FORMAT_OPUS_ACTIVE) ────────
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
static OpusEncoder *opus_encoder = NULL;
static ogg_stream_state ogg_stream;
static long ogg_serialno = -1;
static ogg_packet ogg_opus_head;
static ogg_packet ogg_opus_tags;
static int opus_frame_size_samples = 0;  // SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000
static uint8_t *opus_encoded_buf = NULL;
static ogg_page ogg_page_buf;

// ── Incremental Opus file state ────────────────────────────────────
static File opus_file;                // currently open .opus file
static ogg_int64_t opus_granulepos;   // running granule position across frames
static ogg_int64_t opus_packetno;     // running packet number
static uint32_t opus_encoded_bytes;   // encoded bytes since last flush

// ── OGG page buffer — accumulates pages in memory until ≥4KB before opening SD ──
static uint8_t *ogg_buf = NULL;       // PSRAM buffer for accumulated OGG pages
static uint32_t ogg_buf_pos = 0;      // write position in ogg_buf
static bool pages_flushed = false;    // true after first SD write

// OpusHead/OpusTags generation — delegated to lib/lifelog_core/codec.h

// Flush one OGG page to SD file
static void ogg_write_page(File &file) {
    while (ogg_stream_pageout(&ogg_stream, &ogg_page_buf) != 0) {
        file.write(ogg_page_buf.header, ogg_page_buf.header_len);
        file.write(ogg_page_buf.body, ogg_page_buf.body_len);
    }
}

// Initialize Opus encoder and OGG stream state
static void opus_init() {
    int error;
    opus_encoder = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_VOIP, &error);
    if (error != OPUS_OK || !opus_encoder) {
        LOG_AUDIO(LOG_ERROR, "opus_encoder_create failed: %d", error);
        return;
    }
    opus_encoder_ctl(opus_encoder, OPUS_SET_BITRATE(AUDIO_OPUS_BITRATE));
    opus_encoder_ctl(opus_encoder, OPUS_SET_COMPLEXITY(AUDIO_OPUS_COMPLEXITY));
    opus_encoder_ctl(opus_encoder, OPUS_SET_SIGNAL(OPUS_SIGNAL_VOICE));

    opus_frame_size_samples = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000; // 320

    // OGG stream with random serial number
    ogg_serialno = (long)esp_random();
    ogg_stream_init(&ogg_stream, ogg_serialno);

    // Build header packets (lib/lifelog_core/codec.h)
    generate_opus_head_packet(ogg_opus_head);
    generate_opus_tags_packet(ogg_opus_tags);

    opus_encoded_buf = (uint8_t*)malloc(4000); // max Opus packet

    LOG_AUDIO(LOG_INFO, "Opus encoder ready (frame=%d samples, bitrate=%d)",
              opus_frame_size_samples, AUDIO_OPUS_BITRATE);
}

// Cleanup Opus encoder (called at shutdown)
static void opus_deinit() {
    if (opus_encoder) {
        opus_encoder_destroy(opus_encoder);
        opus_encoder = NULL;
    }
    ogg_stream_clear(&ogg_stream);
    if (ogg_opus_head.packet) { free(ogg_opus_head.packet); ogg_opus_head.packet = NULL; }
    if (ogg_opus_tags.packet) { free(ogg_opus_tags.packet); ogg_opus_tags.packet = NULL; }
    if (opus_encoded_buf) { free(opus_encoded_buf); opus_encoded_buf = NULL; }
}
#endif // AUDIO_FORMAT_OPUS_ACTIVE

// ── audioInit: I2S + AFE + Opus + A/B buffers ─────────────────────

void audioInit() {
    sdMutex = xSemaphoreCreateRecursiveMutex();

    // Initialize PDM microphone via legacy I2S driver
    pdmRxInit();

    // Initialize AFE (VAD + NSNET2 + AGC)
    afeInit();

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
    opus_init();
#endif

    // Allocate contiguous ring buffer in PSRAM
    ring_mutex = xSemaphoreCreateMutex();
    ring_buf = (int16_t *)ps_malloc(RING_CAPACITY * sizeof(int16_t));
    if (!ring_buf) {
        LOG_AUDIO(LOG_ERROR, "Ring buffer malloc failed (%lu bytes)",
                  (unsigned long)(RING_CAPACITY * sizeof(int16_t)));
        return;
    }
    ring_head = 0;
    ring_tail = 0;
    LOG_AUDIO(LOG_INFO, "Ring buffer ready (%d slots × %d samples = %dms, %lu bytes contiguous)",
              RING_SLOTS, RING_CHUNK_SAMPLES,
              (RING_CAPACITY * 1000) / SAMPLE_RATE,
              (unsigned long)(RING_CAPACITY * sizeof(int16_t)));

    // Allocate OGG page buffer in PSRAM (deferred SD open — accumulates until ≥4KB)
    ogg_buf = (uint8_t *)ps_malloc(OGG_BUF_CAPACITY);
    assert(ogg_buf);

    // Upload task — offloads blocking HTTP uploads from writerTask
    uploadQueue = xQueueCreate(8, sizeof(UploadRequest));
    xTaskCreatePinnedToCore(uploadWorkerTask, "uploader", 16384, NULL, 1, &uploadTaskHandle, 1);
    LOG_AUDIO(LOG_INFO, "Upload task started (queue depth=4)");
}

void setWriterTaskHandle(TaskHandle_t handle) {
    writerTaskHandle = handle;
}

void startRecording(uint32_t durationMs) {
    if (recording) return;
    recordDurationMs = durationMs;
    recording = true;
}

void toggleVAD() {
    vadMode = !vadMode;
    LOG_VAD(LOG_INFO, "Mode: %s", vadMode ? "VAD (auto)" : "Fixed duration");
}

// ── AFE feed task — reads I2S, feeds AFE (Core 0) ─────────────────

void afeFeedTask(void *pvParameters) {
    if (!afe_handle || !afe_data) {
        LOG_AFE(LOG_ERROR, "Feed task: AFE not initialized, deleting");
        vTaskDelete(NULL);
        return;
    }
    int chunksize = afe_handle->get_feed_chunksize(afe_data);
    int nch = afe_handle->get_feed_channel_num(afe_data);
    int16_t *buf = (int16_t *)heap_caps_malloc(
        chunksize * nch * sizeof(int16_t), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    assert(buf);
    LOG_AFE(LOG_INFO, "Feed task started (chunksize=%d, nch=%d)", chunksize, nch);

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

// ── AFE fetch task — fetches processed audio + VAD (Core 1) ───────

static void flushBuffer() {
    // Signal writer task to drain whatever is in the ring buffer.
    // The writer checks ring_tail < ring_head to know there's data.
    if (writerTaskHandle) {
        xTaskNotifyGive(writerTaskHandle);
    }
}

static void processAfeResult(afe_fetch_result_t *result) {
    static bool wasVoice = false;
    bool isVoice = (result->vad_state == VAD_SPEECH);

    if (isVoice && !wasVoice) {
        LOG_VAD(LOG_INFO, "Voice started (utterance %lu) vol=%.1f dBFS cache=%d",
                (unsigned long)utteranceId + 1, result->data_volume, result->vad_cache_size);
    } else if (!isVoice && wasVoice) {
        LOG_VAD(LOG_INFO, "Voice ended — signaling writer to drain ring");
    }

    if (isVoice) {
        if (!wasVoice) {
            recording = true;
            utteranceId++;
            chunkIndex = 0;
            isFinal = false;
        }

        // Write to ring buffer at ring_head
        xSemaphoreTake(ring_mutex, portMAX_DELAY);

        // Check if ring has room for one chunk
        uint32_t next_head = (ring_head + RING_CHUNK_SAMPLES) % RING_CAPACITY;
        uint32_t used = (ring_head - ring_tail + RING_CAPACITY) % RING_CAPACITY;
        if (used + RING_CHUNK_SAMPLES > RING_CAPACITY) {
            // Ring full — drop oldest chunk and advance tail
            LOG_AUDIO(LOG_WARN, "Ring overflow: dropping from offset %lu", (unsigned long)ring_tail);
            ring_tail = (ring_tail + RING_CHUNK_SAMPLES) % RING_CAPACITY;
            flushDropCount++;
        }

        // Handle VAD cache (pre-trigger audio — avoids truncating first word)
        uint32_t slotOffset = 0;
        if (result->vad_cache_size > 0 && !wasVoice) {
            int cacheSamples = result->vad_cache_size / sizeof(int16_t);
            if (cacheSamples <= RING_CHUNK_SAMPLES) {
                memcpy(ring_buf + ring_head, result->vad_cache, result->vad_cache_size);
                slotOffset = cacheSamples;
            }
        }

        // Copy AFE-processed audio (NS-cleaned) into ring
        int samples = result->data_size / sizeof(int16_t);
        uint32_t available = RING_CHUNK_SAMPLES - slotOffset;
        uint32_t toCopy = (samples <= available) ? samples : available;
        memcpy(ring_buf + ring_head + slotOffset, result->data, toCopy * sizeof(int16_t));

        ring_head = next_head;
        xSemaphoreGive(ring_mutex);

        totalSamplesCaptured += toCopy;

        // Wake writer to drain ring before it overflows
        if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
    } else if (wasVoice) {
        recording = false;
        isFinal = true;
        flushBuffer();
    }
    wasVoice = isVoice;
}

void afeFetchTask(void *pvParameters) {
    if (!afe_handle || !afe_data) {
        LOG_AFE(LOG_ERROR, "Fetch task: AFE not initialized, deleting");
        vTaskDelete(NULL);
        return;
    }
    LOG_AFE(LOG_INFO, "Fetch task started");

    while (true) {
        afe_fetch_result_t *result = afe_handle->fetch(afe_data);
        if (!result || result->ret_value == ESP_FAIL) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        processAfeResult(result);
    }
}

// ── Deferred SD open API ──────────────────────────────────────────
// Call init_stream when voice begins — buffers in memory, no SD file yet.
// OGG pages accumulate in ogg_buf until ≥4KB, then flush to SD.
// If voice ends before 4KB, discard — no SD writes for short utterances.

static void opus_init_stream() {
    ogg_stream_reset_serialno(&ogg_stream, ogg_serialno);

    opus_granulepos = 0;
    opus_packetno = 2;      // head=0, tags=1, first audio=2
    opus_encoded_bytes = 0;

    // Queue header packets so libogg generates pages with correct sequence numbers
    ogg_opus_head.b_o_s = 1;
    ogg_opus_head.e_o_s = 0;
    ogg_opus_head.granulepos = 0;
    ogg_opus_head.packetno = 0;
    ogg_stream_packetin(&ogg_stream, &ogg_opus_head);

    ogg_opus_tags.b_o_s = 0;
    ogg_opus_tags.e_o_s = 0;
    ogg_opus_tags.granulepos = 0;
    ogg_opus_tags.packetno = 1;
    ogg_stream_packetin(&ogg_stream, &ogg_opus_tags);

    // Drain header pages into buffer immediately
    while (ogg_stream_pageout(&ogg_stream, &ogg_page_buf) != 0) {
        memcpy(ogg_buf + ogg_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
        ogg_buf_pos += ogg_page_buf.header_len;
        memcpy(ogg_buf + ogg_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
        ogg_buf_pos += ogg_page_buf.body_len;
    }

    pages_flushed = false;

    LOG_AUDIO(LOG_INFO, "opus_init_stream: buffering (header=%lu bytes)",
              (unsigned long)ogg_buf_pos);
}

// Opens SD file, writes all buffered OGG pages (headers + audio), transitions to streaming mode.
static void ogg_flush_buffer() {
    if (ogg_buf_pos == 0 || pages_flushed) return;

    char filename[64];
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", fileIndex++);

    sdTake();
    opus_file = SD.open(filename, FILE_WRITE);
    sdGive();

    if (!opus_file) {
        LOG_AUDIO(LOG_ERROR, "ogg_flush_buffer: failed to open %s", filename);
        ogg_buf_pos = 0;
        return;
    }

    sdTake();
    opus_file.write(ogg_buf, ogg_buf_pos);
    sdGive();

    LOG_AUDIO(LOG_INFO, "ogg_flush_buffer: wrote %lu bytes to %s",
              (unsigned long)ogg_buf_pos, filename);

    strcpy(lastSavedFile, filename);
    pages_flushed = true;
    ogg_buf_pos = 0;
}

static int opus_encode_to_buffer(const int16_t* pcm, int samples) {
    const int16_t *ptr = pcm;
    int remaining = samples;

    while (remaining >= opus_frame_size_samples) {
        int encoded_bytes = opus_encode(opus_encoder, ptr,
                                        opus_frame_size_samples,
                                        opus_encoded_buf, 4000);
        if (encoded_bytes > 0) {
            opus_granulepos += (ogg_int64_t)opus_frame_size_samples * 48000 / SAMPLE_RATE;
            ogg_packet op = {0};
            op.packet = opus_encoded_buf;
            op.bytes = encoded_bytes;
            op.b_o_s = 0;
            op.e_o_s = 0;
            op.granulepos = opus_granulepos;
            op.packetno = opus_packetno++;
            ogg_stream_packetin(&ogg_stream, &op);
        }
        ptr += opus_frame_size_samples;
        remaining -= opus_frame_size_samples;
        opus_encoded_bytes += (encoded_bytes > 0) ? encoded_bytes : 0;
    }

    // Drain OGG pages from stream
    while (ogg_stream_pageout(&ogg_stream, &ogg_page_buf) != 0) {
        int page_size = ogg_page_buf.header_len + ogg_page_buf.body_len;

        if (!pages_flushed) {
            // Buffer in memory
            if (ogg_buf_pos + page_size > OGG_BUF_CAPACITY) {
                LOG_AUDIO(LOG_WARN, "OGG buffer full (%lu), flushing early",
                          (unsigned long)ogg_buf_pos);
                ogg_flush_buffer();
            }
            memcpy(ogg_buf + ogg_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
            ogg_buf_pos += ogg_page_buf.header_len;
            memcpy(ogg_buf + ogg_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
            ogg_buf_pos += ogg_page_buf.body_len;

            // ≥4KB threshold → open file and flush
            if (ogg_buf_pos >= 4096 && !pages_flushed) {
                ogg_flush_buffer();
            }
        } else {
            // Already flushed → write directly to file
            sdTake();
            opus_file.write(ogg_page_buf.header, ogg_page_buf.header_len);
            opus_file.write(ogg_page_buf.body, ogg_page_buf.body_len);
            sdGive();
        }
    }

    // Periodic yield when streaming
    if (pages_flushed && opus_encoded_bytes >= 4096) {
        sdTake();
        ogg_write_page(opus_file);
        sdGive();
        opus_encoded_bytes = 0;
        vTaskDelay(pdMS_TO_TICKS(1));
    }

    return remaining;
}

// ── Deferred file close — writer returns immediately after queuing upload ──
static File pendingCloseFile;
static bool hasPendingClose = false;

static void closePendingFile() {
    if (!hasPendingClose) return;
    sdTake();
    pendingCloseFile.close();
    sdGive();
    hasPendingClose = false;
    LOG_AUDIO(LOG_DEBUG, "Deferred file close completed");
}

static void opus_file_end() {
    if (!pages_flushed) {
        // Never reached 4KB — discard, prepare for next stream
        LOG_AUDIO(LOG_INFO, "opus_file_end: discarding %lu bytes (short utterance)",
                  (unsigned long)ogg_buf_pos);
        ogg_buf_pos = 0;
        return;
    }

    // Close any previously deferred file first
    closePendingFile();

    // File open — write EOS and defer close
    sdTake();
    ogg_write_page(opus_file);

    uint8_t eos_data = 0;
    ogg_packet eos_op = {0};
    eos_op.packet = &eos_data;
    eos_op.bytes = 1;
    eos_op.b_o_s = 0;
    eos_op.e_o_s = 1;
    eos_op.granulepos = opus_granulepos;
    eos_op.packetno = opus_packetno;
    ogg_stream_packetin(&ogg_stream, &eos_op);

    if (ogg_stream_flush(&ogg_stream, &ogg_page_buf) != 0) {
        opus_file.write(ogg_page_buf.header, ogg_page_buf.header_len);
        opus_file.write(ogg_page_buf.body, ogg_page_buf.body_len);
    }

    opus_file.flush();

    // Defer the close — writer returns immediately, upload task reads then we close
    pendingCloseFile = opus_file;
    hasPendingClose = true;
    sdGive();

    LOG_AUDIO(LOG_INFO, "opus_file_end: %lu bytes, granule=%lld (close deferred)",
              (unsigned long)pendingCloseFile.size(), (long long)opus_granulepos);
}

// ── Upload worker task — non-blocking upload from queue ────────────

static void uploadWorkerTask(void *pvParameters) {
    UploadRequest req;
    while (true) {
        if (xQueueReceive(uploadQueue, &req, portMAX_DELAY) == pdTRUE) {
            upload_if_connected(req);
        }
    }
}

// ── Write task (reads PSRAM, writes SD, uploads) ──────────────────

void writerTask(void *pvParameters) {
    // Frame-level streaming: no large accumulation buffer.
    // Frame buffer holds remainder < opus_frame_size_samples between drains.
    int16_t frame_buf[512];
    int frame_rem = 0;
    bool prev_recording = false;

    // Local PCM buffer for bulk-draining contiguous ring — allocated in PSRAM.
    const int pcm_buf_capacity = RING_CAPACITY;
    int16_t *pcm_buf = (int16_t *)ps_malloc(pcm_buf_capacity * sizeof(int16_t));
    assert(pcm_buf);

    while (true) {
        // ── Voice start: init OGG stream in memory (no SD file) ──
        if (!prev_recording && recording) {
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
            opus_init_stream();
#else
            char filename[64];
            snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);
            strcpy(lastSavedFile, filename);
#endif
            prev_recording = true;
        }

        // ── Voice end: close file or discard, prepare for next stream ──
        if (prev_recording && !recording) {
            LOG_AUDIO(LOG_INFO, "writer: voice ended, finalizing");
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
            opus_file_end();
#endif
            prev_recording = false;

            if (pages_flushed) {
                UploadRequest req;
                strncpy(req.filename, lastSavedFile, sizeof(req.filename) - 1);
                req.filename[sizeof(req.filename) - 1] = '\0';
                req.utteranceId = utteranceId;
                req.chunkIndex = chunkIndex;
                req.isFinal = isFinal;
                chunkIndex++;
                if (xQueueSend(uploadQueue, &req, 0) != pdTRUE) {
                    LOG_AUDIO(LOG_WARN, "Upload queue full (%lu/%d), skipping %s",
                              (unsigned long)uxQueueMessagesWaiting(uploadQueue), 8, req.filename);
                }
            } else {
                LOG_AUDIO(LOG_INFO, "writer: no file to upload (short utterance)");
            }
        } else {
            // ── Drain ring buffer into local PCM buffer ──
            xSemaphoreTake(ring_mutex, portMAX_DELAY);
            int slots_drained = 0;
            int pcm_count = 0;
            // Carry over remainder from previous drain
            if (frame_rem > 0) {
                memcpy(pcm_buf, frame_buf, frame_rem * sizeof(int16_t));
                pcm_count = frame_rem;
            }
            // Bulk drain: at most 2 memcpy calls
            uint32_t avail = (ring_head - ring_tail + RING_CAPACITY) % RING_CAPACITY;
            uint32_t space = pcm_buf_capacity - pcm_count;
            uint32_t to_drain = (avail < space) ? avail : space;
            // Round down to chunk boundary (AFE always produces full chunks)
            to_drain = (to_drain / RING_CHUNK_SAMPLES) * RING_CHUNK_SAMPLES;

            if (to_drain > 0) {
                uint32_t tail_to_end = RING_CAPACITY - ring_tail;
                uint32_t first = (to_drain < tail_to_end) ? to_drain : tail_to_end;
                memcpy(pcm_buf + pcm_count, ring_buf + ring_tail, first * sizeof(int16_t));
                if (first < to_drain) {
                    memcpy(pcm_buf + pcm_count + first, ring_buf, (to_drain - first) * sizeof(int16_t));
                }
                pcm_count += to_drain;
                slots_drained = to_drain / RING_CHUNK_SAMPLES;
                ring_tail = (ring_tail + to_drain) % RING_CAPACITY;
            }
            // Fill level = chunks in ring before drain
            uint32_t fill = (avail / RING_CHUNK_SAMPLES);
            ringFillLevel = fill;
            if (fill >= RING_SLOTS * 3 / 4) {
                static uint32_t lastFillWarnMs = 0;
                uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
                if (now - lastFillWarnMs >= 2000) {
                    LOG_AUDIO(LOG_WARN, "writer: ring fill %lu/%d (%lu%%)",
                              (unsigned long)fill, RING_SLOTS, (unsigned long)(fill * 100 / RING_SLOTS));
                    lastFillWarnMs = now;
                }
            }
            xSemaphoreGive(ring_mutex);

            if (pcm_count == 0) {
                // Ring empty — block until notification or 50ms timeout.
                ulTaskNotifyTake(pdFALSE, pdMS_TO_TICKS(50));
            }
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
            else if (pcm_count == frame_rem && frame_rem > 0) {
                // No new ring data and only leftover — nothing to encode yet
            }
#endif
            else if (pcm_count > 0) {
                int unconsumed = 0;
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
                totalSamplesWritten += pcm_count - frame_rem;

                // Encode frames, returns unconsumed count
                unconsumed = opus_encode_to_buffer(pcm_buf, pcm_count);
                if (unconsumed > 0) {
                    // Save remainder for next iteration (must be < opus_frame_size_samples)
                    memmove(frame_buf, pcm_buf + (pcm_count - unconsumed),
                            unconsumed * sizeof(int16_t));
                }
                frame_rem = unconsumed;
#else
                // WAV fallback: write file on voice end (handled below)
                totalSamplesWritten += pcm_count;
#endif
            }
        }

        // Always yield — IDLE task needs CPU to feed the task watchdog.
        // 1ms is negligible vs 32ms chunk interval.
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}
