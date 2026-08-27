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

TaskHandle_t getUploadTaskHandle() {
    return uploadTaskHandle;
}

uint32_t getTotalSamplesWritten() { return totalSamplesWritten; }

// ── Upload request (metadata captured at file-close time) ──────────

struct UploadRequest {
    char filename[64];
    uint8_t *mem_ptr;        // NULL if reading from SD
    uint32_t mem_size;
    uint32_t utteranceId;
    uint32_t chunkIndex;
    bool isFinal;
    bool from_sd;
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

// ── PSRAM memory buffer constants ──────────────────────────────────
#define MEM_BUF_INITIAL_SIZE    (64 * 1024)        // 64KB initial
#define MEM_BUF_MAX_SIZE        (4 * 1024 * 1024)  // 4MB max
#define MEM_BUF_GROW_SIZE       (128 * 1024)       // 128KB growth increments
#define SD_FLUSH_THRESHOLD      (2 * 1024 * 1024)  // Flush to SD at 2MB if WiFi down

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
static ogg_int64_t opus_granulepos;   // running granule position across frames
static ogg_int64_t opus_packetno;     // running packet number
static File opus_file;                // currently open .opus file (SD fallback only)

// ── PSRAM memory buffer — growing buffer for entire OGG stream ────
static uint8_t *mem_buf = NULL;       // Growing PSRAM buffer for entire OGG stream
static uint32_t mem_buf_pos = 0;
static uint32_t mem_buf_capacity = 0;
static bool mem_to_sd = false;        // True if flushed to SD (fallback)
static char sd_filename[64];
uint32_t getMemBufUsed() { return mem_buf_pos; }
uint32_t getMemBufCapacity() { return mem_buf_capacity; }
bool isMemToSd() { return mem_to_sd; }

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

// ── PSRAM-first stream init ────────────────────────────────────────
// Allocates growing PSRAM buffer for entire OGG stream.
// No SD file — upload from memory after voice ends.

static void opus_init_stream() {
    ogg_stream_reset_serialno(&ogg_stream, ogg_serialno);

    opus_granulepos = 0;
    opus_packetno = 2;      // head=0, tags=1, first audio=2
    mem_to_sd = false;
    mem_buf_pos = 0;

    // Allocate or reuse growing PSRAM buffer
    if (!mem_buf || mem_buf_capacity < MEM_BUF_INITIAL_SIZE) {
        if (mem_buf) free(mem_buf);
        mem_buf = (uint8_t *)ps_malloc(MEM_BUF_INITIAL_SIZE);
        assert(mem_buf);
        mem_buf_capacity = MEM_BUF_INITIAL_SIZE;
    }

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
        int page_size = ogg_page_buf.header_len + ogg_page_buf.body_len;
        // Ensure capacity for header pages
        while (mem_buf_pos + page_size > mem_buf_capacity) {
            uint32_t new_cap = mem_buf_capacity + MEM_BUF_GROW_SIZE;
            if (new_cap > MEM_BUF_MAX_SIZE) new_cap = MEM_BUF_MAX_SIZE;
            if (new_cap <= mem_buf_capacity) break;  // hit max
            uint8_t *new_buf = (uint8_t *)ps_realloc(mem_buf, new_cap);
            if (!new_buf) break;
            mem_buf = new_buf;
            mem_buf_capacity = new_cap;
        }
        memcpy(mem_buf + mem_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
        mem_buf_pos += ogg_page_buf.header_len;
        memcpy(mem_buf + mem_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
        mem_buf_pos += ogg_page_buf.body_len;
    }

    ESP_LOGD(TAG, "opus_init_stream: PSRAM buffer %luKB (header=%lu bytes)",
             (unsigned long)(mem_buf_capacity / 1024), (unsigned long)mem_buf_pos);
}

// Flush entire mem_buf to SD (fallback when WiFi is down).
static void mem_flush_to_sd() {
    if (mem_buf_pos == 0 || mem_to_sd) return;

    snprintf(sd_filename, sizeof(sd_filename), "/lifelog/rec_%05lu.opus", fileIndex++);

    sdTake();
    opus_file = SD.open(sd_filename, FILE_WRITE);
    sdGive();

    if (!opus_file) {
        ESP_LOGE(TAG, "mem_flush_to_sd: failed to open %s", sd_filename);
        return;
    }

    // Write in 64KB chunks with yields to avoid watchdog
    uint32_t written = 0;
    while (written < mem_buf_pos) {
        uint32_t chunk = mem_buf_pos - written;
        if (chunk > 65536) chunk = 65536;
        sdTake();
        opus_file.write(mem_buf + written, chunk);
        sdGive();
        written += chunk;
        vTaskDelay(pdMS_TO_TICKS(1));
    }

    strcpy(lastSavedFile, sd_filename);
    mem_to_sd = true;

    ESP_LOGI(TAG, "mem_flush_to_sd: wrote %lu bytes to %s",
             (unsigned long)mem_buf_pos, sd_filename);
}

// Grow mem_buf if needed; returns false on failure (hit max or realloc failed).
static bool mem_buf_grow(uint32_t needed) {
    if (mem_buf_pos + needed <= mem_buf_capacity) return true;
    uint32_t new_cap = mem_buf_capacity + MEM_BUF_GROW_SIZE;
    while (new_cap < mem_buf_pos + needed) {
        new_cap += MEM_BUF_GROW_SIZE;
    }
    if (new_cap > MEM_BUF_MAX_SIZE) {
        // Can't grow — caller should flush to SD
        return false;
    }
    uint8_t *new_buf = (uint8_t *)ps_realloc(mem_buf, new_cap);
    if (!new_buf) return false;
    mem_buf = new_buf;
    mem_buf_capacity = new_cap;
    return true;
}

// Encode PCM into Opus, accumulate OGG pages in PSRAM mem_buf.
// Returns unconsumed sample count (< opus_frame_size_samples).
static int opus_encode_to_buffer(const int16_t* pcm, int samples) {
    const int16_t *ptr = pcm;
    int remaining = samples;
    int frames_since_yield = 0;

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

        // Yield every 8 frames to prevent watchdog stalls
        frames_since_yield++;
        if (frames_since_yield >= 8) {
            vTaskDelay(pdMS_TO_TICKS(1));
            frames_since_yield = 0;
        }
    }

    // Drain OGG pages from stream into mem_buf
    while (ogg_stream_pageout(&ogg_stream, &ogg_page_buf) != 0) {
        int page_size = ogg_page_buf.header_len + ogg_page_buf.body_len;

        if (!mem_to_sd) {
            // SD fallback: flush if WiFi is down and buffer exceeds threshold,
            // or if PSRAM can't grow further.
            if (WiFi.status() != WL_CONNECTED && mem_buf_pos > SD_FLUSH_THRESHOLD) {
                ESP_LOGW(TAG, "WiFi down, flushing %lu bytes to SD",
                         (unsigned long)mem_buf_pos);
                mem_flush_to_sd();
            } else if (!mem_buf_grow(page_size)) {
                ESP_LOGW(TAG, "mem_buf full, flushing to SD");
                mem_flush_to_sd();
            }

            if (mem_to_sd) {
                // Write directly to SD file
                sdTake();
                opus_file.write(ogg_page_buf.header, ogg_page_buf.header_len);
                opus_file.write(ogg_page_buf.body, ogg_page_buf.body_len);
                sdGive();
            } else {
                memcpy(mem_buf + mem_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
                mem_buf_pos += ogg_page_buf.header_len;
                memcpy(mem_buf + mem_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
                mem_buf_pos += ogg_page_buf.body_len;
            }
        } else {
            // Already flushed to SD — write directly
            sdTake();
            opus_file.write(ogg_page_buf.header, ogg_page_buf.header_len);
            opus_file.write(ogg_page_buf.body, ogg_page_buf.body_len);
            sdGive();
        }
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
    if (mem_to_sd) {
        // SD fallback — write EOS to SD file, defer close
        closePendingFile();

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
        pendingCloseFile = opus_file;
        hasPendingClose = true;
        sdGive();

        ESP_LOGD(TAG, "opus_file_end: SD fallback %lu bytes, granule=%lld",
                 (unsigned long)pendingCloseFile.size(), (long long)opus_granulepos);
    } else if (mem_buf_pos > 0) {
        // Memory path — finalize EOS packet in buffer, no SD touch
        uint8_t eos_data = 0;
        ogg_packet eos_op = {0};
        eos_op.packet = &eos_data;
        eos_op.bytes = 1;
        eos_op.b_o_s = 0;
        eos_op.e_o_s = 1;
        eos_op.granulepos = opus_granulepos;
        eos_op.packetno = opus_packetno;
        ogg_stream_packetin(&ogg_stream, &eos_op);

        // Flush EOS page into mem_buf
        while (ogg_stream_pageout(&ogg_stream, &ogg_page_buf) != 0) {
            int page_size = ogg_page_buf.header_len + ogg_page_buf.body_len;
            if (!mem_buf_grow(page_size)) {
                // Fallback: flush to SD if can't grow
                mem_flush_to_sd();
                if (mem_to_sd) {
                    sdTake();
                    opus_file.write(ogg_page_buf.header, ogg_page_buf.header_len);
                    opus_file.write(ogg_page_buf.body, ogg_page_buf.body_len);
                    sdGive();
                }
            }
            if (!mem_to_sd) {
                memcpy(mem_buf + mem_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
                mem_buf_pos += ogg_page_buf.header_len;
                memcpy(mem_buf + mem_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
                mem_buf_pos += ogg_page_buf.body_len;
            }
        }

        ESP_LOGD(TAG, "opus_file_end: PSRAM %lu bytes, granule=%lld",
                 (unsigned long)mem_buf_pos, (long long)opus_granulepos);
    } else {
        ESP_LOGD(TAG, "opus_file_end: no data (short utterance)");
    }
}

// ── Upload helper ──────────────────────────────────────────────────

static void upload_if_connected(const UploadRequest &req) {
    if (WiFi.status() == WL_CONNECTED) {
        delay(100);
        bool ok = false;
        if (!req.from_sd && req.mem_ptr) {
            // Memory path — upload from PSRAM buffer (no sdMutex)
            ESP_LOGD(TAG, "Uploading from memory: %s (%luKB, utt=%lu chunk=%lu)...",
                     req.filename, (unsigned long)(req.mem_size / 1024),
                     (unsigned long)req.utteranceId, (unsigned long)req.chunkIndex);
            ok = uploadFileFromMemory(req.mem_ptr, req.mem_size,
                                      req.filename, req.utteranceId,
                                      req.chunkIndex, req.isFinal);
        } else {
            // SD path — upload from file
            ESP_LOGD(TAG, "Uploading from SD: %s (utt=%lu chunk=%lu)...",
                     req.filename, (unsigned long)req.utteranceId, (unsigned long)req.chunkIndex);
            ok = uploadFile(req.filename, req.utteranceId, req.chunkIndex, req.isFinal);
            if (ok) {
                sdTake();
                SD.remove(req.filename);
                sdGive();
                ESP_LOGD(TAG, "Uploaded and deleted %s", req.filename);
            }
        }
        if (!ok) {
            ESP_LOGW(TAG, "Upload failed: %s", req.filename);
        }
    }
    // Free memory buffer after upload attempt (success or fail)
    if (!req.from_sd && req.mem_ptr) {
        free(req.mem_ptr);
    }
    // Close deferred file after upload attempt (SD fallback path)
    if (req.from_sd) {
        closePendingFile();
    }
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

    // mem_buf allocated lazily in opus_init_stream() on first voice start
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

            bool has_data = mem_to_sd ? (strlen(sd_filename) > 0) : (mem_buf_pos > 0);
            if (has_data) {
                UploadRequest req;
                memset(&req, 0, sizeof(req));
                if (mem_to_sd) {
                    // SD fallback path
                    strncpy(req.filename, sd_filename, sizeof(req.filename) - 1);
                    req.mem_ptr = NULL;
                    req.mem_size = 0;
                    req.from_sd = true;
                } else {
                    // Memory path — hand off mem_buf to upload task
                    strncpy(req.filename, lastSavedFile, sizeof(req.filename) - 1);
                    req.mem_ptr = mem_buf;
                    req.mem_size = mem_buf_pos;
                    req.from_sd = false;
                    // Prevent double-free: clear our pointer (upload task owns it now)
                    mem_buf = NULL;
                    mem_buf_pos = 0;
                    mem_buf_capacity = 0;
                }
                req.filename[sizeof(req.filename) - 1] = '\0';
                req.utteranceId = utteranceId;
                req.chunkIndex = chunkIndex;
                req.isFinal = isFinal;
                chunkIndex++;
                if (xQueueSend(uploadQueue, &req, 0) != pdTRUE) {
                    ESP_LOGW(TAG, "Upload queue full (%lu/%d), skipping %s",
                             (unsigned long)uxQueueMessagesWaiting(uploadQueue), 8, req.filename);
                    // Free memory if queue is full
                    if (!req.from_sd && req.mem_ptr) free(req.mem_ptr);
                }
            } else {
                ESP_LOGI(TAG, "writer: no data to upload (short utterance)");
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
