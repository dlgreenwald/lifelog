#include "upload.h"
#include <WiFi.h>
#include <SD.h>
#include "config.h"
#include "audio.h"

bool uploadFile(const char* filename, uint32_t uttId, uint32_t chunkIdx, bool final) {
    if (WiFi.status() != WL_CONNECTED) {
        LOG_UPLOAD(LOG_WARN, "No WiFi connection");
        return false;
    }

    // Quick size check — open, get size, close immediately
    sdTake();
    File probe = SD.open(filename, FILE_READ);
    if (!probe) {
        sdGive();
        LOG_UPLOAD(LOG_ERROR, "Failed to open %s", filename);
        return false;
    }
    uint32_t fileSize = probe.size();
    probe.close();
    sdGive();

    // Discard clips shorter than ~5s — at 24kbps speech ~4KB, headers alone ~200B
    if (fileSize < 4096) {
        LOG_UPLOAD(LOG_INFO, "Discarded short clip: %s (%luB)", filename,
                   (unsigned long)fileSize);
        return true;
    }

    uint32_t uploadStart = millis();
    LOG_UPLOAD(LOG_INFO, "Upload start: %s %luKB",
               filename, (unsigned long)(fileSize / 1024));

    // Build HTTP request — no SD access
    String boundary = "----LifeLogBoundary" + String(millis());
    String contentType = "multipart/form-data; boundary=" + boundary;

    String body = "";
    body += "--" + boundary + "\r\n";
    body += "Content-Disposition: form-data; name=\"utterance_id\"\r\n\r\n";
    body += String(uttId) + "\r\n";
    body += "--" + boundary + "\r\n";
    body += "Content-Disposition: form-data; name=\"chunk_index\"\r\n\r\n";
    body += String(chunkIdx) + "\r\n";
    body += "--" + boundary + "\r\n";
    body += "Content-Disposition: form-data; name=\"is_final\"\r\n\r\n";
    body += final ? "true" : "false";
    body += "\r\n";
    body += "--" + boundary + "\r\n";
    body += "Content-Disposition: form-data; name=\"file\"; filename=\"" + String(filename) + "\"\r\n";
    body += "Content-Type: application/octet-stream\r\n\r\n";

    // Connect to server — no SD access, may take seconds
    WiFiClient client;
    if (!client.connect(SERVER_HOST, SERVER_PORT)) {
        LOG_UPLOAD(LOG_ERROR, "Connection failed");
        return false;
    }

    String headers = "POST " + String(SERVER_PATH) + " HTTP/1.1\r\n";
    headers += "Host: " + String(SERVER_HOST) + ":" + String(SERVER_PORT) + "\r\n";
    headers += "X-API-Key: " + String(API_KEY) + "\r\n";
    headers += "Content-Type: " + contentType + "\r\n";

    uint32_t prefixLen = body.length();
    uint32_t suffixLen = ("\r\n--" + boundary + "--\r\n").length();
    uint32_t contentLength = prefixLen + fileSize + suffixLen;

    headers += "Content-Length: " + String(contentLength) + "\r\n";
    headers += "Connection: close\r\n";
    headers += "\r\n";

    // Send headers and metadata — no SD access
    client.print(headers);
    client.print(body);

    // Open file for streaming — card selected, immediately start reading
    // No idle gap between open and first read
    sdTake();
    File file = SD.open(filename, FILE_READ);
    if (!file) {
        sdGive();
        LOG_UPLOAD(LOG_ERROR, "Failed to reopen %s", filename);
        return false;
    }

    // Stream file in 4K chunks — sdMutex held during read, released during WiFi send
    uint8_t readBuf[4096];
    uint32_t totalSent = 0;
    while (totalSent < fileSize) {
        int n = file.read(readBuf, sizeof(readBuf));
        if (n <= 0) break;
        sdGive();
        client.write(readBuf, n);
        totalSent += n;
        vTaskDelay(pdMS_TO_TICKS(1));
        sdTake();
    }

    file.close();
    sdGive();

    // Send multipart terminator — no SD access
    client.print("\r\n--" + boundary + "--\r\n");

    // Wait for response — no SD access
    uint32_t startTime = millis();
    while (!client.available() && millis() - startTime < 10000) {
        delay(10);
    }

    String response = "";
    while (client.available()) {
        String line = client.readStringUntil('\n');
        response += line + "\n";
    }
    client.stop();

    uint32_t elapsed = millis() - uploadStart;
    if (response.indexOf("200") >= 0) {
        uint32_t rate = (elapsed > 0) ? (fileSize * 1000) / elapsed : 0;
        LOG_UPLOAD(LOG_INFO, "Upload done: %s %lums %luB/s q=%lu", filename,
                   (unsigned long)elapsed, (unsigned long)rate,
                   (unsigned long)getUploadQueueDepth());
        return true;
    } else {
        LOG_UPLOAD(LOG_ERROR, "Upload failed: %s %lums q=%lu %s", filename,
                   (unsigned long)elapsed, (unsigned long)getUploadQueueDepth(),
                   response.substring(0, 80).c_str());
        return false;
    }
}

void uploadAllRecordings() {
    sdTake();
    File root = SD.open("lifelog");
    sdGive();

    if (!root) { LOG_UPLOAD(LOG_ERROR, "Failed to open /lifelog"); return; }

    // Collect files — guard each directory read independently
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

    // Upload and delete — each manages its own sdMutex
    uint32_t orphanId = 0x80000000;
    int uploaded = 0;
    for (int i = 0; i < count; i++) {
        if (uploadFile(paths[i], orphanId++, 0, true)) {
            sdTake();
            SD.remove(paths[i]);
            sdGive();
            uploaded++;
            LOG_UPLOAD(LOG_DEBUG, "Deleted %s", paths[i]);
        }
    }
    LOG_UPLOAD(LOG_INFO, "Done: %d files uploaded", uploaded);
}
