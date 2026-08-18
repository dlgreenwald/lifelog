#include "audio.h"
#include "config.h"
#include "upload.h"
#include "driver/i2s.h"
#include <WiFi.h>
#include "FS.h"
#include "SD.h"
#include "SPI.h"

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
#include <opus.h>
#include <ogg/ogg.h>
#endif

// WAV header size
#define WAV_HEADER_SIZE 44
#define SAMPLE_BITS 16
#define VOLUME_GAIN 3

// Global state
volatile bool recording = false;
volatile bool vadMode = true;
volatile bool sdBusy = false;
uint32_t fileIndex = 0;
uint32_t recordDurationMs = 5000;
char lastSavedFile[64] = {0};
static TaskHandle_t writerTaskHandle = NULL;

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

uint32_t getWriterStallCount() { return writerStallCount; }
uint32_t getWriterStallMaxMs() { return writerStallMaxMs; }
uint32_t getDmaPartialCount() { return dmaPartialCount; }
uint32_t getFlushDropCount() { return flushDropCount; }
uint32_t getTotalSamplesCaptured() { return totalSamplesCaptured; }
uint32_t getTotalSamplesWritten() { return totalSamplesWritten; }

// ── WAV header (from Seeed Studio guide) ───────────────────────────

#ifdef AUDIO_FORMAT_WAV_ACTIVE
static void generate_wav_header(uint8_t *wav_header, uint32_t wav_size, uint32_t sample_rate) {
    uint32_t file_size = wav_size + WAV_HEADER_SIZE - 8;
    uint32_t byte_rate = SAMPLE_RATE * SAMPLE_BITS / 8;
    
    const uint8_t set_wav_header[] = {
        'R', 'I', 'F', 'F', // ChunkID
        file_size, file_size >> 8, file_size >> 16, file_size >> 24, // ChunkSize
        'W', 'A', 'V', 'E', // Format
        'f', 'm', 't', ' ', // Subchunk1ID
        0x10, 0, 0, 0, // Subchunk1Size (16 for PCM)
        0x01, 0, // AudioFormat (PCM)
        0x01, 0, // NumChannels (mono)
        sample_rate, sample_rate >> 8, sample_rate >> 16, sample_rate >> 24, // SampleRate
        byte_rate, byte_rate >> 8, byte_rate >> 16, byte_rate >> 24, // ByteRate
        0x02, 0, // BlockAlign
        0x10, 0, // BitsPerSample
        'd', 'a', 't', 'a', // Subchunk2ID
        wav_size, wav_size >> 8, wav_size >> 16, wav_size >> 24 // Subchunk2Size
    };
    
    memcpy(wav_header, set_wav_header, WAV_HEADER_SIZE);
}
#endif // AUDIO_FORMAT_WAV_ACTIVE

// ── RMS computation for VAD ────────────────────────────────────────

static float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

// ── Forward declarations ──────────────────────────────────────────
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
static void opus_init();
static void write_opus_file(int16_t* pcm, uint32_t samples, const char* filename);
#endif
static void upload_if_connected(const char* filename);
static float compute_median(float* history, int count);

// ── Median filter (used by VAD) ───────────────────────────────────

static float compute_median(float* history, int count) {
    float sorted[count];
    memcpy(sorted, history, count * sizeof(float));
    for (int i = 0; i < count - 1; i++) {
        for (int j = i + 1; j < count; j++) {
            if (sorted[i] > sorted[j]) {
                float tmp = sorted[i];
                sorted[i] = sorted[j];
                sorted[j] = tmp;
            }
        }
    }
    return sorted[count / 2];
}

// ── Upload helper ──────────────────────────────────────────────────

static void upload_if_connected(const char* filename) {
    if (WiFi.status() == WL_CONNECTED) {
        delay(100);
        LOG_AUDIO(LOG_INFO, "Uploading %s...", filename);
        if (uploadFile(filename, utteranceId, chunkIndex, isFinal)) {
            delay(300);
            SD.remove(filename);
            LOG_AUDIO(LOG_INFO, "Uploaded and deleted %s", filename);
        }
    }
}

// ── Public API ─────────────────────────────────────────────────────

void audioInit() {
    // No queue needed — A/B buffers + task notifications handle data flow
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
    opus_init();
#endif
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

// ── A/B Buffer State ───────────────────────────────────────────────

static int16_t* bufA = NULL;
static int16_t* bufB = NULL;
static int16_t* audioBuf = NULL;   // Buffer audio task writes to
static int16_t* writeBuf = NULL;   // Buffer write task reads from
static uint32_t audioCount = 0;    // Samples in audio buffer
static uint32_t writeCount = 0;    // Samples in write buffer
static volatile bool bufferReady = false;  // Audio buffer full
static volatile bool writeDone = true;     // Write task idle
static uint32_t bufCapacity = 0;   // Max samples per buffer

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

// Build OpusHead identification header (RFC 7845)
static void generate_opus_head_packet() {
    uint8_t header[19] = {0};
    // Magic bytes
    header[0] = 'O'; header[1] = 'p'; header[2] = 'u'; header[3] = 's';
    header[4] = 'H'; header[5] = 'e'; header[6] = 'a'; header[7] = 'd';
    header[8] = 1;            // Version
    header[9] = 1;            // Channel count (mono)
    header[10] = 0; header[11] = 15; // Pre-skip: 3840 samples (80ms at 48kHz) little-endian
    header[12] = (uint8_t)(SAMPLE_RATE);
    header[13] = (uint8_t)(SAMPLE_RATE >> 8);
    header[14] = (uint8_t)(SAMPLE_RATE >> 16);
    header[15] = (uint8_t)(SAMPLE_RATE >> 24);
    header[16] = 0; header[17] = 0; // Output gain: 0
    header[18] = 0;            // Channel mapping family: 0

    memset(&ogg_opus_head, 0, sizeof(ogg_opus_head));
    ogg_opus_head.packet = (unsigned char*)malloc(19);
    memcpy(ogg_opus_head.packet, header, 19);
    ogg_opus_head.bytes = 19;
}

// Build OpusTags comment header (RFC 7845)
static void generate_opus_tags_packet() {
    const char *vendor = "LifeLog ESP32";
    uint32_t vendor_len = strlen(vendor);
    uint32_t tag_data_len = 8 + 4 + vendor_len + 4; // magic + vendor_len + vendor + tag_count(0)
    uint8_t *tag_buf = (uint8_t*)malloc(tag_data_len);

    // "OpusTags" magic
    tag_buf[0] = 'O'; tag_buf[1] = 'p'; tag_buf[2] = 'u'; tag_buf[3] = 's';
    tag_buf[4] = 'T'; tag_buf[5] = 'a'; tag_buf[6] = 'g'; tag_buf[7] = 's';
    // Vendor string length (little-endian)
    tag_buf[8]  = (uint8_t)(vendor_len);
    tag_buf[9]  = (uint8_t)(vendor_len >> 8);
    tag_buf[10] = (uint8_t)(vendor_len >> 16);
    tag_buf[11] = (uint8_t)(vendor_len >> 24);
    // Vendor string
    memcpy(tag_buf + 12, vendor, vendor_len);
    // Tag count = 0
    tag_buf[12 + vendor_len] = 0;
    tag_buf[12 + vendor_len + 1] = 0;
    tag_buf[12 + vendor_len + 2] = 0;
    tag_buf[12 + vendor_len + 3] = 0;

    memset(&ogg_opus_tags, 0, sizeof(ogg_opus_tags));
    ogg_opus_tags.packet = tag_buf;
    ogg_opus_tags.bytes = tag_data_len;
}

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

    // Build header packets
    generate_opus_head_packet();
    generate_opus_tags_packet();

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

// ── Audio capture task with VAD (records continuously) ─────────────

void audioTask(void *pvParameters) {
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
        .ws_io_num = I2S_MIC_CLK,    // PDM CLK = GPIO42 (mapped via fsPin)
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

    // Allocate A/B buffers in PSRAM — 5 seconds each
    // Multiple 200ms DMA reads accumulate before each swap/save
    uint32_t bufBytes = (SAMPLE_RATE * SAMPLE_BITS / 8) * 5;
    bufA = (int16_t*)ps_malloc(bufBytes);
    bufB = (int16_t*)ps_malloc(bufBytes);
    if (!bufA || !bufB) {
        LOG_AUDIO(LOG_ERROR, "PSRAM malloc failed");
        return;
    }
    bufCapacity = bufBytes / sizeof(int16_t);
    audioBuf = bufA;
    writeBuf = bufB;
    audioCount = 0;
    writeCount = 0;
    writeDone = true;
    LOG_AUDIO(LOG_INFO, "A/B buffers ready (%d samples each)", bufCapacity);

    // VAD state
    bool voiceActive = false;
    uint32_t silenceStartMs = 0;  // millis() when silence began
    float startThreshold = VAD_THRESHOLD;
    uint32_t startTime = millis();
    uint32_t startupGraceMs = 2000;

    // RMS analysis — 200ms DMA-aligned reads (no accumulation needed)
    int analysisCapacity = SAMPLE_RATE * VAD_ANALYSIS_MS / 1000;  // 3200 samples
    int16_t* analysisBuffer = (int16_t*)ps_malloc(analysisCapacity * sizeof(int16_t));
    if (!analysisBuffer) {
        LOG_AUDIO(LOG_ERROR, "Analysis buffer PSRAM malloc failed");
        return;
    }
    float smoothedRMS = 0;

    // Median filter
    #define MEDIAN_SAMPLES 5
    float rmsHistory[MEDIAN_SAMPLES] = {0};
    int rmsIndex = 0;
    int rmsCount = 0;

    while (true) {
        // DMA fill: CPU sleeps until 3200 samples available in ring buffer
        size_t bytesRead = 0;
        i2s_read(I2S_NUM_0, analysisBuffer, analysisCapacity * sizeof(int16_t),
                 &bytesRead, portMAX_DELAY);
        if (bytesRead == 0) continue;

        int samplesRead = bytesRead / 2;
        uint32_t expectedBytes = analysisCapacity * sizeof(int16_t);
        if (bytesRead < expectedBytes) {
            dmaPartialCount++;
            LOG_AUDIO(LOG_WARN, "DMA partial read: %d/%d bytes (overflow likely)",
                      (int)bytesRead, (int)expectedBytes);
        }

        // Compute RMS on RAW audio (before gain) for VAD
        smoothedRMS = computeRMS(analysisBuffer, samplesRead);

        // Apply volume gain in-place (recording path uses this buffer)
        for (int i = 0; i < samplesRead; i++) {
            analysisBuffer[i] <<= VOLUME_GAIN;
        }

        // Copy gain-applied audio to recording buffer
        if (recording) {
            // Flush when buffer full
            if (audioCount + samplesRead > bufCapacity) {
                uint32_t waitStart = millis();
                while (!writeDone) { vTaskDelay(pdMS_TO_TICKS(5)); }
                uint32_t waitMs = millis() - waitStart;
                if (waitMs > 0) {
                    writerStallCount++;
                    if (waitMs > writerStallMaxMs) writerStallMaxMs = waitMs;
                    LOG_AUDIO(LOG_WARN, "Writer stall: waited %lu ms", (unsigned long)waitMs);
                }
                int16_t* tmp = writeBuf;
                writeBuf = audioBuf;
                writeCount = audioCount;
                audioBuf = tmp;
                audioCount = 0;
                bufferReady = true;
                writeDone = false;
                if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
            }

            memcpy(audioBuf + audioCount, analysisBuffer, bytesRead);
            audioCount += samplesRead;
            totalSamplesCaptured += samplesRead;
        }

        // Median filter
        rmsHistory[rmsIndex] = smoothedRMS;
        rmsIndex = (rmsIndex + 1) % MEDIAN_SAMPLES;
        if (rmsCount < MEDIAN_SAMPLES) rmsCount++;

        float medianRMS = compute_median(rmsHistory, rmsCount);

        // Log RMS periodically
        static uint32_t lastRecLog = 0;
        uint32_t now = millis();
        if (now - lastRecLog >= 1000) {
            LOG_VAD(LOG_INFO, "RMS=%.0f, median=%.0f", smoothedRMS, medianRMS);
            lastRecLog = now;
        }

        // VAD logic — use median for robustness against spikes
        if (!voiceActive && medianRMS > startThreshold && (now - startTime) > startupGraceMs) {
            voiceActive = true;
            silenceStartMs = now;  // reset silence tracker
            audioCount = 0;
            recording = true;
            utteranceId++;           // Next utterance
            chunkIndex = 0;          // Reset chunk counter
            isFinal = false;         // Not final yet
            LOG_VAD(LOG_INFO, "Voice started (median=%.0f, start=%.0f)", medianRMS, startThreshold);
        } else if (voiceActive) {
            if (medianRMS > startThreshold) {
                silenceStartMs = now;  // voice still present — reset silence timer
            }

            uint32_t silenceMs = now - silenceStartMs;

            // Log RMS silence periodically
            static uint32_t lastSilenceLog = 0;
            if (now - lastSilenceLog >= 1000) {
                LOG_VAD(LOG_INFO, "silence=%d ms / %d", silenceMs, VAD_SILENCE_MS);
                lastSilenceLog = now;
            }

            if (silenceMs >= VAD_SILENCE_MS) {
                voiceActive = false;
                recording = false;
                isFinal = true;          // Signal this is the last chunk
                // Flush remaining partial buffer
                if (audioCount > 0 && writeDone) {
                    int16_t* tmp = writeBuf;
                    writeBuf = audioBuf;
                    writeCount = audioCount;
                    audioBuf = tmp;
                    audioCount = 0;
                    bufferReady = true;
                    writeDone = false;
                    if (writerTaskHandle) xTaskNotifyGive(writerTaskHandle);
                } else {
                    if (audioCount > 0) {
                        flushDropCount++;
                        LOG_AUDIO(LOG_WARN, "Flush drop: %lu samples discarded (writeDone=%d)",
                                  (unsigned long)audioCount, (int)writeDone);
                    }
                    audioCount = 0;
                }
                LOG_VAD(LOG_INFO, "Voice ended (silence %d ms)", silenceMs);
                lastRecLog = 0;
                // Keep median filter state — don't reset between recordings
            }
        }
    }
}

// ── Opus file writer ──────────────────────────────────────────────

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
static void write_opus_file(int16_t* pcm, uint32_t samples, const char* filename) {
    File file = SD.open(filename, FILE_WRITE);
    if (!file) {
        LOG_AUDIO(LOG_ERROR, "Failed to open %s", filename);
        return;
    }

    // Reset OGG stream for new file
    ogg_stream_reset_serialno(&ogg_stream, ogg_serialno);

    // Write OpusHead packet
    ogg_opus_head.b_o_s = 1;
    ogg_opus_head.e_o_s = 0;
    ogg_opus_head.granulepos = 0;
    ogg_opus_head.packetno = 0;
    ogg_stream_packetin(&ogg_stream, &ogg_opus_head);
    ogg_write_page(file);

    // Write OpusTags packet
    ogg_opus_tags.b_o_s = 0;
    ogg_opus_tags.e_o_s = 0;
    ogg_opus_tags.granulepos = 0;
    ogg_opus_tags.packetno = 1;
    ogg_stream_packetin(&ogg_stream, &ogg_opus_tags);
    ogg_write_page(file);

    // Encode audio in 20ms frames
    int16_t *pcm_ptr = pcm;
    int samples_remaining = samples;
    ogg_int64_t granulepos = 0;
    ogg_int64_t packetno = 2;

    while (samples_remaining >= opus_frame_size_samples) {
        int encoded_bytes = opus_encode(opus_encoder, pcm_ptr,
                                       opus_frame_size_samples,
                                       opus_encoded_buf, 4000);
        if (encoded_bytes > 0) {
            granulepos += (ogg_int64_t)opus_frame_size_samples * 48000 / SAMPLE_RATE;
            ogg_packet op = {0};
            op.packet = opus_encoded_buf;
            op.bytes = encoded_bytes;
            op.b_o_s = 0;
            op.e_o_s = 0;
            op.granulepos = granulepos;
            op.packetno = packetno++;
            ogg_stream_packetin(&ogg_stream, &op);
            ogg_write_page(file);
        }
        pcm_ptr += opus_frame_size_samples;
        samples_remaining -= opus_frame_size_samples;
    }

    // Mark end of stream
    ogg_packet eos_op = {0};
    eos_op.bytes = 0;
    eos_op.b_o_s = 0;
    eos_op.e_o_s = 1;
    eos_op.granulepos = granulepos;
    eos_op.packetno = packetno;
    ogg_stream_packetin(&ogg_stream, &eos_op);

    // Flush remaining pages
    ogg_write_page(file);

    file.flush();
    delay(150);
    uint32_t fileSize = file.size();
    file.close();
    delay(150);

    LOG_AUDIO(LOG_INFO, "Saved: %s (%d bytes)", filename, fileSize);
}
#endif

// ── Write task (reads PSRAM, writes SD, uploads) ──────────────────

void writerTask(void *pvParameters) {
    while (true) {
        // Block until audio task signals a buffer is ready
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        // Write the ready buffer to SD
        uint32_t samplesToWrite = writeCount;
        totalSamplesWritten += samplesToWrite;
        uint32_t totalBytes = samplesToWrite * 2;

        char filename[64];
        sdBusy = true;

#ifdef AUDIO_FORMAT_OPUS_ACTIVE
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", fileIndex++);
        write_opus_file(writeBuf, samplesToWrite, filename);
#else
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", fileIndex++);
        File file = SD.open(filename, FILE_WRITE);
        if (file) {
            uint8_t wav_header[WAV_HEADER_SIZE];
            generate_wav_header(wav_header, totalBytes, SAMPLE_RATE);
            file.write(wav_header, WAV_HEADER_SIZE);
            file.write((uint8_t*)writeBuf, totalBytes);
            file.flush();
            delay(150);
            file.close();
            delay(150);
            LOG_AUDIO(LOG_INFO, "Saved: %s (%d bytes)", filename, totalBytes + WAV_HEADER_SIZE);
        } else {
            LOG_AUDIO(LOG_ERROR, "Failed to open %s", filename);
        }
#endif

        upload_if_connected(filename);
        chunkIndex++;  // Next chunk in this utterance
        sdBusy = false;

        bufferReady = false;
        writeDone = true;
    }
}
