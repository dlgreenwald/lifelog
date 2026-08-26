// Writer — consumer (reads ring buffer, encodes Opus, writes SD, uploads)
// Moved from audio.cpp for TAG granularity (TAG = "WRITER").

#include "writer.h"
#include "audio.h"
#include "config.h"
#include "upload.h"
#include <WiFi.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"
#include "esp_log.h"

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
#include <opus.h>
#include <ogg/ogg.h>
#endif

#include "lifelog_core/codec.h"

static const char* TAG = "WRITER";

// ── Upload state ──────────────────────────────────────────────────
static QueueHandle_t uploadQueue = NULL;
static TaskHandle_t uploadTaskHandle = NULL;

// Buffer health counter
static uint32_t totalSamplesWritten = 0;

uint32_t getUploadQueueDepth() {
    return uploadQueue ? uxQueueMessagesWaiting(uploadQueue) : 0;
}

uint32_t getTotalSamplesWritten() { return totalSamplesWritten; }

// ── Upload request (metadata captured at file-close time) ──────────

struct UploadRequest {
    char filename[64];
    uint32_t utteranceId;
    uint32_t chunkIndex;
    bool isFinal;
};

// ── Forward declarations ──────────────────────────────────────────
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
static void opus_init();
static void opus_deinit();
static void opus_init_stream();
static int opus_encode_to_buffer(const int16_t* pcm, int samples);
static void opus_file_end();
#endif
static void closePendingFile();

// ── OGG page buffer capacity ──────────────────────────────────────
#define OGG_BUF_CAPACITY 16384  // 16KB PSRAM buffer for accumulated OGG pages before SD open

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
        ESP_LOGE(TAG, "opus_encoder_create failed: %d", error);
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

    ESP_LOGD(TAG, "Opus encoder ready (frame=%d samples, bitrate=%d)",
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

    ESP_LOGD(TAG, "opus_init_stream: buffering (header=%lu bytes)",
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
        ESP_LOGE(TAG, "ogg_flush_buffer: failed to open %s", filename);
        ogg_buf_pos = 0;
        return;
    }

    sdTake();
    opus_file.write(ogg_buf, ogg_buf_pos);
    sdGive();

    ESP_LOGI(TAG, "ogg_flush_buffer: wrote %lu bytes to %s",
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
                ESP_LOGW(TAG, "OGG buffer full (%lu), flushing early",
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
    ESP_LOGD(TAG, "Deferred file close completed");
}

static void opus_file_end() {
    if (!pages_flushed) {
        // Never reached 4KB — discard, prepare for next stream
        ESP_LOGD(TAG, "opus_file_end: discarding %lu bytes (short utterance)",
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

    ESP_LOGD(TAG, "opus_file_end: %lu bytes, granule=%lld (close deferred)",
             (unsigned long)pendingCloseFile.size(), (long long)opus_granulepos);
}

// ── Upload helper ──────────────────────────────────────────────────

static void upload_if_connected(const UploadRequest &req) {
    if (WiFi.status() == WL_CONNECTED) {
        delay(100);
        ESP_LOGD(TAG, "Uploading %s (utt=%lu chunk=%lu)...",
                 req.filename, (unsigned long)req.utteranceId, (unsigned long)req.chunkIndex);
        if (uploadFile(req.filename, req.utteranceId, req.chunkIndex, req.isFinal)) {
            sdTake();
            SD.remove(req.filename);
            sdGive();
            ESP_LOGD(TAG, "Uploaded and deleted %s", req.filename);
        } else {
            ESP_LOGW(TAG, "Upload failed: %s", req.filename);
        }
    }
    // Close deferred file after upload attempt (success or fail)
    closePendingFile();
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

// ── Writer init — creates upload queue, spawns upload task ─────────

void writerInit() {
    uploadQueue = xQueueCreate(8, sizeof(UploadRequest));
    xTaskCreatePinnedToCore(uploadWorkerTask, "uploader", 16384, NULL, 1, &uploadTaskHandle, 1);
    ESP_LOGD(TAG, "Upload task started (queue depth=8)");

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
    opus_init();
#endif

    // Allocate OGG page buffer in PSRAM (deferred SD open — accumulates until ≥4KB)
    ogg_buf = (uint8_t *)ps_malloc(OGG_BUF_CAPACITY);
    assert(ogg_buf);
}

// ── Write task (reads PSRAM, writes SD, uploads) ──────────────────

void writerTask(void *pvParameters) {
    // Frame-level streaming: no large accumulation buffer.
    // Frame buffer holds remainder < opus_frame_size_samples between drains.
    int16_t frame_buf[512];
    int frame_rem = 0;
    bool prev_recording = false;

    // Local PCM buffer for accumulating ring items — allocated in PSRAM.
    const int pcm_buf_capacity = RING_NUM_ITEMS * (RING_ITEM_BYTES / sizeof(int16_t));
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
            ESP_LOGD(TAG, "writer: voice ended, finalizing");
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
                    ESP_LOGW(TAG, "Upload queue full (%lu/%d), skipping %s",
                             (unsigned long)uxQueueMessagesWaiting(uploadQueue), 8, req.filename);
                }
            } else {
                ESP_LOGI(TAG, "writer: no file to upload (short utterance)");
            }
        } else {
            // ── Drain ring buffer into local PCM buffer ──
            int pcm_count = 0;
            // Carry over remainder from previous drain
            if (frame_rem > 0) {
                memcpy(pcm_buf, frame_buf, frame_rem * sizeof(int16_t));
                pcm_count = frame_rem;
            }

            // Drain all available items (each ≤ RING_ITEM_BYTES)
            while (pcm_count < pcm_buf_capacity) {
                size_t itemSize;
                void *item = xRingbufferReceive(audioRingBuf, &itemSize, 0);
                if (!item) break;
                int samples = itemSize / sizeof(int16_t);
                if (pcm_count + samples > pcm_buf_capacity) {
                    vRingbufferReturnItem(audioRingBuf, item);
                    break;  // pcm_buf full — process what we have
                }
                memcpy(pcm_buf + pcm_count, item, itemSize);
                pcm_count += samples;
                vRingbufferReturnItem(audioRingBuf, item);
            }

            // Fill level for dashboard
            UBaseType_t uxItemsWaiting = 0;
            vRingbufferGetInfo(audioRingBuf, NULL, NULL, NULL, NULL, &uxItemsWaiting);
            uint32_t fill = (uint32_t)uxItemsWaiting;
            if (fill >= RING_NUM_ITEMS * 3 / 4) {
                static uint32_t lastFillWarnMs = 0;
                uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
                if (now - lastFillWarnMs >= 2000) {
                    ESP_LOGW(TAG, "writer: ring fill %lu/%d (%lu%%)",
                             (unsigned long)fill, RING_NUM_ITEMS, (unsigned long)(fill * 100 / RING_NUM_ITEMS));
                    lastFillWarnMs = now;
                }
            }

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
