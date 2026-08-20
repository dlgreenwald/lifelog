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

    // Open file and get size — brief sdMutex hold
    sdTake();
    File file = SD.open(filename, FILE_READ);
    if (!file) {
        sdGive();
        LOG_UPLOAD(LOG_ERROR, "Failed to open %s", filename);
        return false;
    }
    uint32_t fileSize = file.size();
    sdGive();

    LOG_UPLOAD(LOG_INFO, "Uploading %s (%lu bytes)...", filename, (unsigned long)fileSize);

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

    // Connect to server — no SD access
    WiFiClient client;
    if (!client.connect(SERVER_HOST, SERVER_PORT)) {
        LOG_UPLOAD(LOG_ERROR, "Connection failed");
        sdTake();
        file.close();
        sdGive();
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

    // Stream file in 4K chunks — sdMutex held only during each read(),
    // released while WiFi sends so writerTask can drain the ring buffer.
    // Yield after each chunk so I2S DMA can use the shared FSPI bus.
    uint8_t readBuf[4096];
    uint32_t totalSent = 0;
    while (totalSent < fileSize) {
        sdTake();
        int n = file.read(readBuf, sizeof(readBuf));
        sdGive();
        if (n <= 0) break;
        client.write(readBuf, n);
        totalSent += n;
        vTaskDelay(pdMS_TO_TICKS(1));
    }

    // Close file — brief sdMutex hold
    sdTake();
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

    if (response.indexOf("200") >= 0) {
        LOG_UPLOAD(LOG_INFO, "Success: %s", filename);
        return true;
    } else {
        LOG_UPLOAD(LOG_ERROR, "Failed: %s", response.substring(0, 100).c_str());
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
