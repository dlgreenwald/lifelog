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

bool uploadFile(const char* filename, uint32_t uttId, uint32_t chunkIdx, bool final) {
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

    if (fileSize < 4096) {
        ESP_LOGI(TAG, "Discarded short clip: %s (%luB)", filename, (unsigned long)fileSize);
        return true;
    }

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
                SD.remove(filename);
                sdGive();
                bool ok = uploadFileFromMemory(buf, fileSize, filename, uttId, chunkIdx, final);
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
    prefix += final ? "true" : "false";
    prefix += "\r\n";

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
        ESP_LOGI(TAG, "Upload done: %s %lums %luB/s q=%lu", filename,
                   (unsigned long)elapsed, (unsigned long)rate,
                   (unsigned long)getUploadQueueDepth());
        return true;
    } else {
        ESP_LOGE(TAG, "Upload failed: %s %lums q=%lu status=%d", filename,
                   (unsigned long)elapsed, (unsigned long)getUploadQueueDepth(), httpStatus);
        return false;
    }
}

void uploadAllRecordings() {
    sdTake();
    File root = SD.open("lifelog");
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
            snprintf(paths[count], sizeof(paths[count]), "/lifelog/%s", f.name());
            count++;
        }
    }
    sdTake();
    root.close();
    sdGive();

    uint32_t orphanId = 0x80000000;
    int uploaded = 0;
    for (int i = 0; i < count; i++) {
        if (uploadFile(paths[i], orphanId++, 0, true)) {
            sdTake();
            SD.remove(paths[i]);
            sdGive();
            uploaded++;
            ESP_LOGD(TAG, "Deleted %s", paths[i]);
        }
    }
    ESP_LOGI(TAG, "Done: %d files uploaded", uploaded);
}
bool uploadFileFromMemory(const uint8_t *data, uint32_t size,
                          const char *filename, uint32_t uttId,
                          uint32_t chunkIdx, bool final) {
    if (WiFi.status() != WL_CONNECTED) {
        ESP_LOGW(TAG, "No WiFi connection");
        return false;
    }

    if (size < 4096) {
        ESP_LOGI(TAG, "Discarded short clip: %s (%luB)", filename, (unsigned long)size);
        return true;
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
    prefix += final ? "true" : "false";
    prefix += "\r\n";

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
        ESP_LOGI(TAG, "Upload done: %s %lums %luB/s q=%lu", filename,
                   (unsigned long)elapsed, (unsigned long)rate,
                   (unsigned long)getUploadQueueDepth());
        return true;
    } else {
        ESP_LOGE(TAG, "Upload failed: %s %lums q=%lu status=%d", filename,
                   (unsigned long)elapsed, (unsigned long)getUploadQueueDepth(), httpStatus);
        return false;
    }
}
