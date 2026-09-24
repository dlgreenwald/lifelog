#include "upload.h"
#include <WiFi.h>
#include <SD.h>
#include <esp_http_client.h>
extern "C" esp_err_t esp_crt_bundle_attach(void *conf);
#include "config.h"
#include "settings.h"
#include "audio.h"
#include "writer.h"
#include "oauth2_client.h"

static const char* TAG = "UPLOAD";

// Forward declaration — defined later in this file
static time_t _parse_epoch_from_filename(const char *filename);

// ── SD directory cache — populated once, served from PSRAM ──────────

#define SD_CACHE_MAX_ENTRIES 64

struct SdCacheEntry {
    char filename[64];
    time_t epoch;
};

static struct {
    SdCacheEntry entries[SD_CACHE_MAX_ENTRIES];
    uint16_t count;
    bool valid;
    bool wasFull;  // true if cache hit 64-entry limit at any point
} sdDirCache;

// Alphanumeric qsort comparison — rec_<epoch>_<index>.opus filenames sort chronologically
static int _cache_cmp(const void *a, const void *b) {
    return strcmp(((const SdCacheEntry *)a)->filename, ((const SdCacheEntry *)b)->filename);
}

void sdDirCacheInit() {
    memset(&sdDirCache, 0, sizeof(sdDirCache));

    File root = SD.open("/lifelog");
    if (!root) {
        ESP_LOGW(TAG, "sdDirCache: failed to open /lifelog");
        return;
    }

    uint16_t n = 0;
    while (n < SD_CACHE_MAX_ENTRIES) {
        File f = root.openNextFile();
        if (!f) break;
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
        if (!String(f.name()).endsWith(".opus")) { f.close(); continue; }
#else
        if (!String(f.name()).endsWith(".wav")) { f.close(); continue; }
#endif
        const char *name = f.name();
        if (strncmp(name, "lifelog/", 8) == 0) name += 8;
        snprintf(sdDirCache.entries[n].filename, sizeof(sdDirCache.entries[n].filename),
                 "/lifelog/%s", name);
        sdDirCache.entries[n].epoch = _parse_epoch_from_filename(name);
        n++;
        f.close();
    }
    root.close();

    // Sort alphanumerically — stable, fast, zero allocation
    if (n > 1) {
        qsort(sdDirCache.entries, n, sizeof(SdCacheEntry), _cache_cmp);
    }
    sdDirCache.count = n;
    sdDirCache.valid = true;
    sdDirCache.wasFull = false;

    ESP_LOGI(TAG, "sdDirCache: scanned %u entries from /lifelog", n);
}

const char *sdDirCacheGetEntry(uint16_t i, time_t *outEpoch) {
    if (!sdDirCache.valid || i >= sdDirCache.count) return nullptr;
    if (outEpoch) *outEpoch = sdDirCache.entries[i].epoch;
    return sdDirCache.entries[i].filename;
}

uint16_t sdDirCacheGetCount() {
    return sdDirCache.valid ? sdDirCache.count : 0;
}

void sdDirCacheRemove(const char *filename) {
    if (!sdDirCache.valid || sdDirCache.count == 0) return;
    for (uint16_t i = 0; i < sdDirCache.count; i++) {
        if (strcmp(sdDirCache.entries[i].filename, filename) == 0) {
            // Shift remaining entries down
            for (uint16_t j = i; j < sdDirCache.count - 1; j++) {
                sdDirCache.entries[j] = sdDirCache.entries[j + 1];
            }
            sdDirCache.count--;
            ESP_LOGD(TAG, "sdDirCache: removed %s (%u remaining)", filename, sdDirCache.count);

            // If cache drained after being full, rebuild to pick up overflow files
            if (sdDirCache.count == 0 && sdDirCache.wasFull) {
                ESP_LOGI(TAG, "sdDirCache: drained after overflow, rebuilding");
                sdDirCache.wasFull = false;
                sdDirCacheInit();
            }
            return;
        }
    }
}

void sdDirCacheInvalidate() {
    sdDirCache.valid = false;
    sdDirCache.count = 0;
}

bool sdDirCacheAdd(const char *fullPath, time_t epoch) {
    if (!sdDirCache.valid) return false;
    if (sdDirCache.count >= SD_CACHE_MAX_ENTRIES) {
        sdDirCache.wasFull = true;  // mark for rebuild when cache drains
        return false;
    }
    snprintf(sdDirCache.entries[sdDirCache.count].filename,
             sizeof(sdDirCache.entries[0].filename), "%s", fullPath);
    sdDirCache.entries[sdDirCache.count].epoch = epoch;
    sdDirCache.count++;
    return true;
}

bool uploadFile(const char* filename, uint32_t uttId, uint32_t chunkIdx, bool isFinal,
                time_t recordedAt, uint32_t startMs, uint32_t endMs) {
    if (WiFi.status() != WL_CONNECTED) {
        ESP_LOGW(TAG, "No WiFi connection");
        return false;
    }

    // Quick size check — single lock
    sdTake();
    File probe = SD.open(filename, FILE_READ);
    if (!probe) { sdGive(); ESP_LOGE(TAG, "Failed to open %s", filename); return false; }
    uint32_t fileSize = probe.size();
    probe.close();
    sdGive();

    uint32_t uploadStart = millis();
    ESP_LOGD(TAG, "Upload start: %s %luKB", filename, (unsigned long)(fileSize / 1024));

    // Tier 1: If file fits in PSRAM, read entire file with one lock, delegate
    size_t freePsram = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    if (fileSize <= freePsram / 2) {
        sdTake();
        uint8_t *buf = (uint8_t *)ps_malloc(fileSize);
        if (buf) {
            File file = SD.open(filename, FILE_READ);
            if (file) {
                file.read(buf, fileSize);
                file.close();
                sdGive();
                bool ok = uploadFileFromMemory(buf, fileSize, filename, uttId, chunkIdx, isFinal, recordedAt, startMs, endMs);

                if (ok) {
                    SD.remove(filename);
                    sdDirCacheRemove(filename);
                }

                free(buf);
                return ok;
            }
        }
        sdGive();
        ESP_LOGD(TAG, "PSRAM alloc failed, falling back to SD streaming");
    }

    // Tier 2: Stream from SD in 64KB chunks, one lock per chunk
    if (!oauth2Client().hasValidToken()) {
        ESP_LOGW(TAG, "No valid OAuth token, skipping upload");
        return false;
    }

    // Build multipart metadata prefix
    String boundary = "----LifeLogBoundary" + String(millis());
    String prefix = "";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"utterance_id\"\r\n\r\n";
    prefix += String(uttId) + "\r\n";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"chunk_index\"\r\n\r\n";
    prefix += String(chunkIdx) + "\r\n";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"is_final\"\r\n\r\n";
    prefix += isFinal ? "true" : "false";
    prefix += "\r\n";
    if (recordedAt > 0) {
        char recordedAtStr[32];
        snprintf(recordedAtStr, sizeof(recordedAtStr), "%ld", (long)recordedAt);
        prefix += "--" + boundary + "\r\n";
        prefix += "Content-Disposition: form-data; name=\"recorded_at\"\r\n\r\n";
        prefix += recordedAtStr;
        prefix += "\r\n";
    }
    // System uptime ms for gap analysis between utterances
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"utterance_start_ms\"\r\n\r\n";
    prefix += String(startMs) + "\r\n";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"utterance_end_ms\"\r\n\r\n";
    prefix += String(endMs) + "\r\n";

    // File part header
    String fileHeader = "--" + boundary + "\r\n";
    fileHeader += "Content-Disposition: form-data; name=\"file\"; filename=\"" + String(filename) + "\"\r\n";
    fileHeader += "Content-Type: application/octet-stream\r\n\r\n";
    String suffix = "\r\n--" + boundary + "--\r\n";
    uint32_t contentLength = prefix.length() + fileHeader.length() + fileSize + suffix.length();

    // Build URL — detect scheme from serverHost
    char url[256];
    bool useTls = false;
    if (strncmp(deviceSettings.serverHost, "https://", 8) == 0) {
        useTls = true;
        snprintf(url, sizeof(url), "%s:%u%s",
                 deviceSettings.serverHost, deviceSettings.serverPort, deviceSettings.serverPath);
    } else if (strncmp(deviceSettings.serverHost, "http://", 7) == 0) {
        snprintf(url, sizeof(url), "%s:%u%s",
                 deviceSettings.serverHost, deviceSettings.serverPort, deviceSettings.serverPath);
    } else {
        // Plain IP or hostname — default to http
        snprintf(url, sizeof(url), "http://%s:%u%s",
                 deviceSettings.serverHost, deviceSettings.serverPort, deviceSettings.serverPath);
    }

    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = 30000;
    config.buffer_size = 4096;
    config.buffer_size_tx = 4096;
    if (useTls) {
        config.skip_cert_common_name_check = true;
    }

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "Failed to init HTTP client");
        return false;
    }

    // Set Content-Type
    char contentType[128];
    snprintf(contentType, sizeof(contentType), "multipart/form-data; boundary=%s", boundary.c_str());
    esp_http_client_set_header(client, "Content-Type", contentType);

    // Attach to OAuth proxy (handles Bearer injection + 401 retry)
    oauth2Client().setTransport(client);

    // Allocate 64KB chunk buffer
    uint8_t *chunkBuf = (uint8_t *)ps_malloc(64 * 1024);
    if (!chunkBuf) chunkBuf = (uint8_t *)malloc(64 * 1024);
    if (!chunkBuf) {
        ESP_LOGE(TAG, "Failed to alloc upload buffer");
        esp_http_client_cleanup(client);
        return false;
    }

    // Open connection — proxy injects Bearer header
    int retryLimit = 2;
    int httpStatus = 0;

    for (int attempt = 0; attempt < retryLimit; attempt++) {
        oauth2Client().open(contentLength);

        // Write metadata prefix
        oauth2Client().write(prefix.c_str(), prefix.length());

        // Write file part header
        oauth2Client().write(fileHeader.c_str(), fileHeader.length());

        // Stream file from SD in 64KB chunks — one lock per chunk
        sdTake();
        File file = SD.open(filename, FILE_READ);
        sdGive();
        if (!file) {
            ESP_LOGE(TAG, "Failed to open %s for reading", filename);
            free(chunkBuf);
            oauth2Client().close();
            esp_http_client_cleanup(client);
            return false;
        }

        uint32_t totalSent = 0;
        while (totalSent < fileSize) {
            sdTake();
            int n = file.read(chunkBuf, 64 * 1024);
            sdGive();
            if (n <= 0) break;
            oauth2Client().write(chunkBuf, n);
            totalSent += n;
            vTaskDelay(pdMS_TO_TICKS(1));
        }
        sdTake();
        file.close();
        sdGive();

        // Write suffix
        oauth2Client().write(suffix.c_str(), suffix.length());

        // Fetch response
        oauth2Client().fetch_headers();
        httpStatus = oauth2Client().get_status_code();

        if (httpStatus == -401) {
            // Token was refreshed, retry
            ESP_LOGD(TAG, "Auth failed, retrying with new token");
            continue;
        }
        break;  // Got final status
    }

    free(chunkBuf);
    oauth2Client().close();
    esp_http_client_cleanup(client);

    uint32_t elapsed = millis() - uploadStart;
    if (httpStatus == 200) {
        uint32_t rate = (elapsed > 0) ? (fileSize * 1000) / elapsed : 0;
        ESP_LOGI(TAG, "Upload done: %s %lums %luB/s q=%lu voice=%lu-%lums",
                   filename, (unsigned long)elapsed, (unsigned long)rate,
                   (unsigned long)getUploadQueueDepth(),
                   (unsigned long)startMs, (unsigned long)endMs);

        // Delete file from SD and cache on successful upload
        sdTake();
        SD.remove(filename);
        sdGive();
        sdDirCacheRemove(filename);

        return true;
    } else {
        ESP_LOGE(TAG, "Upload failed: %s %lums q=%lu status=%d", filename,
                   (unsigned long)elapsed, (unsigned long)getUploadQueueDepth(), httpStatus);
        return false;
    }
}

void uploadAllRecordings() {
    sdTake();
    File root = SD.open("/lifelog");
    sdGive();
    if (!root) { ESP_LOGE(TAG, "Failed to open /lifelog"); return; }

    char paths[64][64];
    int count = 0;
    while (count < 64) {
        sdTake();
        File f = root.openNextFile();
        sdGive();
        if (!f) break;
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
        if (String(f.name()).endsWith(".opus")) {
#else
        if (String(f.name()).endsWith(".wav")) {
#endif
            // Strip "lifelog/" prefix if present (ESP32 SD returns full relative paths)
            const char *fname = f.name();
            if (strncmp(fname, "lifelog/", 8) == 0) fname += 8;
            snprintf(paths[count], sizeof(paths[count]), "/lifelog/%s", fname);
            count++;
        }
    }
    sdTake();
    root.close();
    sdGive();

    uint32_t orphanId = 0x80000000;
    int uploaded = 0;
    for (int i = 0; i < count; i++) {
        if (uploadFile(paths[i], orphanId++, 0, true, 0, 0, 0)) {
            sdTake();
            SD.remove(paths[i]);
            sdGive();
            uploaded++;
            ESP_LOGD(TAG, "Deleted %s", paths[i]);
        }
    }
    ESP_LOGI(TAG, "Done: %d files uploaded", uploaded);
}
// ── Requirement 2: Auto batch upload task ──────────────────────────

static TaskHandle_t autoUploadTaskHandle = NULL;

// Parse epoch from filename like "rec_1726926612_042.opus" → returns 1726926612, or 0 if invalid
static time_t _parse_epoch_from_filename(const char *filename) {
    // Strip path prefix
    const char *base = strrchr(filename, '/');
    base = base ? base + 1 : filename;
    // Expected format: rec_<epoch>_<index>.opus
    if (strncmp(base, "rec_", 4) != 0) return 0;
    char *end = nullptr;
    time_t epoch = strtoll(base + 4, &end, 10);
    if (end == base + 4 || epoch <= 0) return 0;
    return epoch;
}

static void autoUploadTask(void *pvParameters) {
    const TickType_t interval = pdMS_TO_TICKS(30000);  // 30 seconds
    while (true) {
        vTaskDelay(interval);

        if (WiFi.status() != WL_CONNECTED) continue;

        sdTake();
        File root = SD.open("/lifelog");
        if (!root) { sdGive(); continue; }

        char paths[32][64];
        time_t epochs[32];
        int count = 0;
        while (count < 32) {
            sdTake();
            File f = root.openNextFile();
            sdGive();
            if (!f) break;
#ifdef AUDIO_FORMAT_OPUS_ACTIVE
            if (String(f.name()).endsWith(".opus")) {
#else
            if (String(f.name()).endsWith(".wav")) {
#endif
                // Strip "lifelog/" prefix if present (ESP32 SD returns full relative paths)
                const char *fname = f.name();
                if (strncmp(fname, "lifelog/", 8) == 0) fname += 8;
                snprintf(paths[count], sizeof(paths[count]), "/lifelog/%s", fname);
                epochs[count] = _parse_epoch_from_filename(fname);
                count++;
            }
        }
        sdTake();
        root.close();
        sdGive();
        if (count == 0) {
            ESP_LOGI(TAG, "Auto-upload: no files on SD, queue=%lu", (unsigned long)getUploadQueueDepth());
            continue;
        }
        ESP_LOGI(TAG, "Auto-upload: found %d files on SD, queue=%lu", count,
                 (unsigned long)getUploadQueueDepth());

        uint32_t orphanId = 0x80000000;
        for (int i = 0; i < count; i++) {
            if (uploadFile(paths[i], orphanId++, 0, true, epochs[i], 0, 0)) {
                sdTake();
                SD.remove(paths[i]);
                sdGive();
                ESP_LOGI(TAG, "Auto-uploaded and deleted: %s", paths[i]);
            }
            vTaskDelay(pdMS_TO_TICKS(500));  // brief delay between files
        }
    }
}

void startAutoUploadTask() {
    xTaskCreatePinnedToCore(autoUploadTask, "autoUpload", 12288, NULL, 1, &autoUploadTaskHandle, 1);
    ESP_LOGI(TAG, "Auto-upload task started (every 30s, core 1, stack 12288)");
}

static TaskHandle_t uploadMonitorTaskHandle = NULL;

// ── Upload monitor: logs WiFi + cache status, uploads files when WiFi up ──

static void uploadMonitorTask(void *pvParameters) {
    const TickType_t interval = pdMS_TO_TICKS(30000);  // 30 seconds
    uint32_t orphanId = 0x80000000;

    while (true) {
        vTaskDelay(interval);

        bool wifi = WiFi.status() == WL_CONNECTED;
        uint16_t cached = sdDirCacheGetCount();

        ESP_LOGI(TAG, "uploadMonitor: WiFi=%s cache=%u", wifi ? "up" : "DOWN", cached);

        if (!wifi || cached == 0) continue;

        // Upload all cached files — always process index 0 since remove shifts the array
        while (sdDirCacheGetCount() > 0 && WiFi.status() == WL_CONNECTED) {
            time_t epoch = 0;
            const char *path = sdDirCacheGetEntry(0, &epoch);

            ESP_LOGI(TAG, "uploadMonitor: attempting %s", path);

            if (uploadFile(path, orphanId++, 0, true, epoch, 0, 0)) {
                sdTake();
                SD.remove(path);
                sdGive();
                sdDirCacheRemove(path);
                ESP_LOGI(TAG, "uploadMonitor: uploaded and deleted %s", path);
            } else {
                ESP_LOGW(TAG, "uploadMonitor: upload failed, stopping");
                break;
            }

            vTaskDelay(pdMS_TO_TICKS(500));  // brief delay between files
        }
    }
}

void startUploadMonitorTask() {
    xTaskCreatePinnedToCore(uploadMonitorTask, "uploadMon", 12288, NULL, 1, &uploadMonitorTaskHandle, 1);
    ESP_LOGI(TAG, "Upload monitor task started (every 30s, core 1, stack 12288)");
}

bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                          const char* filename, uint32_t uttId,
                          uint32_t chunkIdx, bool isFinal, time_t recordedAt,
                          uint32_t startMs, uint32_t endMs) {
    if (WiFi.status() != WL_CONNECTED) {
        ESP_LOGW(TAG, "No WiFi connection");
        return false;
    }

    uint32_t uploadStart = millis();
    ESP_LOGD(TAG, "Upload from memory: %s %luKB", filename, (unsigned long)(size / 1024));

    // Check auth — OAuth token required
    if (!oauth2Client().hasValidToken()) {
        ESP_LOGW(TAG, "No valid OAuth token, skipping upload");
        return false;
    }

    // Build multipart metadata prefix
    String boundary = "----LifeLogBoundary" + String(millis());
    String prefix = "";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"utterance_id\"\r\n\r\n";
    prefix += String(uttId) + "\r\n";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"chunk_index\"\r\n\r\n";
    prefix += String(chunkIdx) + "\r\n";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"is_final\"\r\n\r\n";
    prefix += isFinal ? "true" : "false";
    prefix += "\r\n";
    if (recordedAt > 0) {
        char recordedAtStr[32];
        snprintf(recordedAtStr, sizeof(recordedAtStr), "%ld", (long)recordedAt);
        prefix += "--" + boundary + "\r\n";
        prefix += "Content-Disposition: form-data; name=\"recorded_at\"\r\n\r\n";
        prefix += recordedAtStr;
        prefix += "\r\n";
    }
    // System uptime ms for gap analysis between utterances
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"utterance_start_ms\"\r\n\r\n";
    prefix += String(startMs) + "\r\n";
    prefix += "--" + boundary + "\r\n";
    prefix += "Content-Disposition: form-data; name=\"utterance_end_ms\"\r\n\r\n";
    prefix += String(endMs) + "\r\n";

    // File part header
    String fileHeader = "--" + boundary + "\r\n";
    fileHeader += "Content-Disposition: form-data; name=\"file\"; filename=\"" + String(filename) + "\"\r\n";
    fileHeader += "Content-Type: application/octet-stream\r\n\r\n";

    String suffix = "\r\n--" + boundary + "--\r\n";
    uint32_t contentLength = prefix.length() + fileHeader.length() + size + suffix.length();

    // Build URL — detect scheme from serverHost
    char url[256];
    bool useTls = false;
    if (strncmp(deviceSettings.serverHost, "https://", 8) == 0) {
        useTls = true;
        snprintf(url, sizeof(url), "%s:%u%s",
                 deviceSettings.serverHost, deviceSettings.serverPort, deviceSettings.serverPath);
    } else if (strncmp(deviceSettings.serverHost, "http://", 7) == 0) {
        snprintf(url, sizeof(url), "%s:%u%s",
                 deviceSettings.serverHost, deviceSettings.serverPort, deviceSettings.serverPath);
    } else {
        snprintf(url, sizeof(url), "http://%s:%u%s",
                 deviceSettings.serverHost, deviceSettings.serverPort, deviceSettings.serverPath);
    }

    esp_http_client_config_t config = {};
    config.url = url;
    config.method = HTTP_METHOD_POST;
    config.timeout_ms = 30000;
    config.buffer_size = 4096;
    config.buffer_size_tx = 4096;
    if (useTls) {
        config.skip_cert_common_name_check = true;
    }

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        ESP_LOGE(TAG, "Failed to init HTTP client");
        return false;
    }

    // Set Content-Type
    char contentType[128];
    snprintf(contentType, sizeof(contentType), "multipart/form-data; boundary=%s", boundary.c_str());
    esp_http_client_set_header(client, "Content-Type", contentType);

    // Attach to OAuth proxy (handles Bearer injection + 401 retry)
    oauth2Client().setTransport(client);

    // Open connection — proxy injects Bearer header
    int retryLimit = 2;
    int httpStatus = 0;

    for (int attempt = 0; attempt < retryLimit; attempt++) {
        oauth2Client().open(contentLength);

        // Write metadata prefix
        oauth2Client().write(prefix.c_str(), prefix.length());

        // Write file part header
        oauth2Client().write(fileHeader.c_str(), fileHeader.length());

        // Stream data from memory (no SD, no sdMutex)
        uint32_t totalSent = 0;
        while (totalSent < size) {
            uint32_t chunk = size - totalSent;
            if (chunk > 4096) chunk = 4096;
            oauth2Client().write(data + totalSent, chunk);
            totalSent += chunk;
            vTaskDelay(pdMS_TO_TICKS(1));
        }

        // Write suffix
        oauth2Client().write(suffix.c_str(), suffix.length());

        // Fetch response
        oauth2Client().fetch_headers();
        httpStatus = oauth2Client().get_status_code();

        if (httpStatus == -401) {
            // Token was refreshed, retry
            ESP_LOGD(TAG, "Auth failed, retrying with new token");
            continue;
        }
        break;  // Got final status
    }

    oauth2Client().close();
    esp_http_client_cleanup(client);

    uint32_t elapsed = millis() - uploadStart;
    if (httpStatus == 200) {
        uint32_t rate = (elapsed > 0) ? (size * 1000) / elapsed : 0;
        ESP_LOGI(TAG, "Upload done: %s %lums %luB/s q=%lu voice=%lu-%lums",
                   filename, (unsigned long)elapsed, (unsigned long)rate,
                   (unsigned long)getUploadQueueDepth(),
                   (unsigned long)startMs, (unsigned long)endMs);
        return true;
    } else {
        ESP_LOGE(TAG, "Upload failed: %s %lums q=%lu status=%d", filename,
                   (unsigned long)elapsed, (unsigned long)getUploadQueueDepth(), httpStatus);
        return false;
    }
}
