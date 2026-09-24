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
#include "lifelog_core/filename.h"
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
    time_t recorded_at;      // UTC epoch seconds; 0 if clock invalid
    uint32_t start_ms;      // system uptime ms when voice start was detected
    uint32_t end_ms;        // system uptime ms when voice end was detected
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
#define MEM_BUF_INITIAL_SIZE    (1 * 1024 * 1024)        // 64KB initial
#define MEM_BUF_MAX_SIZE        (1 * 1024 * 1024)  // 4MB max
#define MEM_BUF_GROW_SIZE       (128 * 1024)       // 128KB growth increments
#define SD_FLUSH_THRESHOLD      (MEM_BUF_MAX_SIZE - 256 * 1024)  // Flush to SD with 384KB headroom for growth during drain + EOS

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
static bool firstSdFlush = true;     // true at utterance start; false after first flush to SD
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

// Epoch (from time()) at utterance start — used for stable filename across flushes
static time_t s_utterance_start_epoch = 0;

static void opus_init_stream() {
    firstSdFlush = true;   // reset flush gate for new utterance
    ogg_stream_reset_serialno(&ogg_stream, ogg_serialno);

    opus_granulepos = 0;
    opus_packetno = 2;      // head=0, tags=1, first audio=2
    mem_to_sd = false;  // Reset so this utterance's flushes create/append to its own file
    mem_buf_pos = 0;
    s_utterance_start_epoch = time(nullptr);

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

// Grow mem_buf if needed; returns true if data fits (either grew or had room),
// false only if growth was needed but failed (hit max or realloc failed).
static bool mem_buf_grow(uint32_t needed) {
    if (mem_buf_pos + needed <= mem_buf_capacity) {
        return true;  // Already fits — no growth needed
    }
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

    // Drain OGG pages from stream into growing PSRAM buffer.
    // Threshold flushes are handled by the caller in the main loop condition.
    while (ogg_stream_pageout(&ogg_stream, &ogg_page_buf) != 0) {
        int page_size = ogg_page_buf.header_len + ogg_page_buf.body_len;
        if (!mem_buf_grow(page_size)) {
            ESP_LOGE(TAG, "mem_buf_grow failed — mem_buf_pos=%lu needed=%d",
                     (unsigned long)mem_buf_pos, page_size);
        }
        memcpy(mem_buf + mem_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
        mem_buf_pos += ogg_page_buf.header_len;
        memcpy(mem_buf + mem_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
        mem_buf_pos += ogg_page_buf.body_len;
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
    if (mem_buf_pos == 0) {
        ESP_LOGD(TAG, "opus_file_end: no data (short utterance)");
        return;
    }

    // Finalize EOS packet into PSRAM buffer
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
            // PSRAM exhausted — drop this segment rather than write past allocation
            ESP_LOGE(TAG, "opus_file_end: PSRAM exhausted, discarding segment");
            mem_buf_pos = 0;
            return;
        }
        memcpy(mem_buf + mem_buf_pos, ogg_page_buf.header, ogg_page_buf.header_len);
        mem_buf_pos += ogg_page_buf.header_len;
        memcpy(mem_buf + mem_buf_pos, ogg_page_buf.body, ogg_page_buf.body_len);
        mem_buf_pos += ogg_page_buf.body_len;
    }

    ESP_LOGD(TAG, "opus_file_end: PSRAM %lu bytes, granule=%lld",
             (unsigned long)mem_buf_pos, (long long)opus_granulepos);
}

// ── Write current mem_buf to SD as a single file ─────────────────────

static void write_file_to_sd(time_t utterance_epoch, uint32_t segment) {
    if (mem_buf_pos == 0) return;

    // Close any pending file from a prior segment first
    closePendingFile();

    if (sdMutex == NULL) {
        ESP_LOGE(TAG, "write_file_to_sd: sdMutex is NULL");
        return;
    }

    // Generate filename: rec_<epoch>_<segment>.opus
    generateFilenameUtc(sd_filename, sizeof(sd_filename), utterance_epoch, segment, true);
    char full_path[64];
    snprintf(full_path, sizeof(full_path), "/lifelog/%s", sd_filename);

    uint32_t t0 = millis();

    sdTake();
    ESP_LOGI(TAG, "write_file_to_sd: %lu bytes to %s", (unsigned long)mem_buf_pos, full_path);
    File f = SD.open(full_path, FILE_WRITE);
    if (!f) {
        sdGive();
        ESP_LOGE(TAG, "write_file_to_sd: failed to open %s", full_path);
        return;
    }

    uint32_t written = 0;
    while (written < mem_buf_pos) {
        uint32_t chunk = mem_buf_pos - written;
        if (chunk > 65536) chunk = 65536;
        f.write(mem_buf + written, chunk);
        written += chunk;
        vTaskDelay(pdMS_TO_TICKS(1));  // yield to avoid watchdog
    }

    // Explicitly flush before closing. Arduino SD library's close() only calls
    // fclose() — it does NOT call fsync() — so data can be lost.
    // File::flush() calls fflush() + fsync() internally (workaround for issue #1293).
    // Note: both flush() and close() return void, so errors are silently ignored.
    f.flush();
    f.close();
    ESP_LOGI(TAG, "write_file_to_sd: closed %s", full_path);
    sdGive();

    strcpy(lastSavedFile, full_path);
    mem_buf_pos = 0;

    ESP_LOGI(TAG, "write_file_to_sd: done %lu bytes in %lums",
             (unsigned long)written, (unsigned long)(millis() - t0));

    // Add to SD dir cache so autoUploadTask finds it without a rescan
    sdDirCacheAdd(full_path, utterance_epoch);
}

// ── Persist: upload from memory, or write to SD if WiFi unavailable ─

static bool persist_or_upload_file(time_t utterance_epoch, uint32_t segment) {
    // Short utterance — mem_buf_pos == 0 means no audio captured
    if (mem_buf_pos == 0) {
        ESP_LOGI(TAG, "persist_or_upload_file: short utterance, discarding");
        closePendingFile();
        return false;
    }

    // Close any pending SD file from prior segment before new operations
    closePendingFile();

    if (WiFi.status() != WL_CONNECTED) {
        ESP_LOGW(TAG, "persist_or_upload_file: WiFi down, writing segment %lu to SD", (unsigned long)segment);
        write_file_to_sd(utterance_epoch, segment);
        // After writing, mem_buf_pos = 0; queue the SD file below
        // WiFi-down: mark that we need to queue the SD file
        // Fall through to queue the SD file for later upload
    }

    // Attempt upload from PSRAM memory
    if (WiFi.status() == WL_CONNECTED) {
        char filename[64];
        generateFilenameUtc(filename, sizeof(filename), utterance_epoch, segment, true);
        ESP_LOGD(TAG, "persist_or_upload_file: uploading %s (%luKB, voice=%lu-%lums)...",
                 filename, (unsigned long)(mem_buf_pos / 1024),
                 (unsigned long)listenStartMs, (unsigned long)millis());
        bool ok = uploadFileFromMemory(mem_buf, mem_buf_pos,
                                      filename, utteranceId,
                                      chunkIndex, isFinal, utterance_epoch,
                                      listenStartMs, millis());
        if (ok) {
            ESP_LOGD(TAG, "persist_or_upload_file: upload success, segment %lu", (unsigned long)segment);
            // mem_buf = NULL;
            mem_buf_pos = 0;
            // mem_buf_capacity = 0;
            return true;
        }
        ESP_LOGW(TAG, "persist_or_upload_file: upload failed, writing segment %lu to SD",
                 (unsigned long)segment);
        write_file_to_sd(utterance_epoch, segment);
    }

    // Reset memory state — next segment starts fresh
    // mem_buf = NULL;
    mem_buf_pos = 0;
    // mem_buf_capacity = 0;
    // Reset mem_to_sd so next utterance starts fresh (not appending to this file)
    mem_to_sd = false;

    return false;
}

void writerInit() {

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
    uint32_t s_segment = 0;  // segment counter per utterance

    // Local PCM buffer for accumulating ring items — allocated in PSRAM.
    const int pcm_buf_capacity = RING_NUM_ITEMS * (RING_ITEM_BYTES / sizeof(int16_t));
    int16_t *pcm_buf = (int16_t *)ps_malloc(pcm_buf_capacity * sizeof(int16_t));
    assert(pcm_buf);

    while (true) {
        // Health log — once per second
        static uint32_t lastHealthLogMs = 0;
        uint32_t nowMs = millis();
        if (recording && nowMs - lastHealthLogMs >= 1000) {
            ESP_LOGI(TAG, "writer: healthy mem_buf_pos=%lu/%lu",
                        (unsigned long)mem_buf_pos, (unsigned long)mem_buf_capacity);
            lastHealthLogMs = nowMs;
        }

        // ── Voice start detected ──────────────────────────────────────
        if (!prev_recording && recording) {
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
            opus_init_stream();
#else
            char filename[64];
            time_t now = time(nullptr);
            if (now > 0) {
                char base[64];
                generateFilenameUtc(base, sizeof(base), now, fileIndex++, false);
                snprintf(filename, sizeof(filename), "/lifelog/%s", base);
            } else {
                snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);
            }
            strcpy(lastSavedFile, filename);
#endif
            prev_recording = true;
            s_segment = 0;
        }

        // ── Voice end detected *OR* buffer full ───────────────────────
        // Two independent flush triggers:
        //   1. prev_recording && !recording  — utterance ended
        //   2. recording && mem_buf_pos > SD_FLUSH_THRESHOLD — buffer full mid-utterance
        if ((prev_recording && !recording) || (recording && mem_buf_pos > SD_FLUSH_THRESHOLD)) {
            ESP_LOGE(TAG, "writer: flush block%s",
                     (!recording) ? " (voice end)" : " (buffer threshold)");
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
            // Drain any remaining ring items before finalizing the segment
            int drain_count = 0;
            if (frame_rem > 0) {
                memcpy(pcm_buf, frame_buf, frame_rem * sizeof(int16_t));
                drain_count = frame_rem;
                frame_rem = 0;
            }
            while (drain_count < pcm_buf_capacity) {
                size_t itemSize;
                void *item = xRingbufferReceive(audioRingBuf, &itemSize, 0);
                if (!item) break;
                int samples = itemSize / sizeof(int16_t);
                if (drain_count + samples > pcm_buf_capacity) {
                    vRingbufferReturnItem(audioRingBuf, item);
                    break;
                }
                memcpy(pcm_buf + drain_count, item, itemSize);
                drain_count += samples;
                vRingbufferReturnItem(audioRingBuf, item);
            }
            if (drain_count > 0) {
                opus_encode_to_buffer(pcm_buf, drain_count);
            }

            opus_file_end();

            // Persist: upload from memory, or write to SD if WiFi unavailable
            persist_or_upload_file(s_utterance_start_epoch, s_segment);

            chunkIndex++;   // each segment gets its own chunkIndex
            s_segment++;
#endif
            // Reset prev_recording only on true voice end (not buffer-threshold flush)
            if (!recording) {
                prev_recording = false;
            }
        }
        // ── Normal audio drain ────────────────────────────────────────
        else {
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
                    break;
                }
                memcpy(pcm_buf + pcm_count, item, itemSize);
                pcm_count += samples;
                vRingbufferReturnItem(audioRingBuf, item);
            }

            // Warning: AFE is outrunning the writer — check BEFORE drain
            UBaseType_t uxItemsWaiting = 0;
            vRingbufferGetInfo(audioRingBuf, NULL, NULL, NULL, NULL, &uxItemsWaiting);
            uint32_t fill = (uint32_t)uxItemsWaiting;
            if (fill >= RING_NUM_ITEMS * 3 / 4) {
                static uint32_t lastFillWarnMs = 0;
                uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
                if (now - lastFillWarnMs >= 2000) {
                    ESP_LOGW(TAG, "writer: ring fill %lu/%d (%lu%%)",
                             (unsigned long)fill, RING_NUM_ITEMS,
                             (unsigned long)(fill * 100 / RING_NUM_ITEMS));
                    lastFillWarnMs = now;
                }
            }

            if (pcm_count == 0) {
                // Ring empty — block until notification or 50ms timeout
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
                unconsumed = opus_encode_to_buffer(pcm_buf, pcm_count);
                if (unconsumed > 0) {
                    memmove(frame_buf, pcm_buf + (pcm_count - unconsumed),
                            unconsumed * sizeof(int16_t));
                }
                frame_rem = unconsumed;
#else
                totalSamplesWritten += pcm_count;
#endif
            }
        }

        // Always yield — IDLE task needs CPU to feed the task watchdog.
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}
