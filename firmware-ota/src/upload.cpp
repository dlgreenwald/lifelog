#include "upload.h"
#include <WiFi.h>
#include <SD.h>
#include "config.h"

// Server configuration
#define SERVER_HOST    "192.168.68.190"
#define SERVER_PORT    8443
#define SERVER_PATH    "/api/v1/upload"
#define API_KEY        "lifelog-key"

extern RemoteDebug Debug;
#define LOG(fmt, ...) do { \
    Serial.printf(fmt "\n", ##__VA_ARGS__); \
    debugD(fmt, ##__VA_ARGS__); \
} while(0)

bool uploadFile(const char* filename) {
    if (WiFi.status() != WL_CONNECTED) {
        LOG("[UPLOAD] No WiFi connection");
        return false;
    }

    File file = SD.open(filename, FILE_READ);
    if (!file) {
        LOG("[UPLOAD] Failed to open %s", filename);
        return false;
    }

    uint32_t fileSize = file.size();
    LOG("[UPLOAD] Uploading %s (%d bytes)...", filename, fileSize);

    String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + SERVER_PATH;
    String boundary = "----LifeLogBoundary" + String(millis());
    String contentType = "multipart/form-data; boundary=" + boundary;

    String body = "";
    body += "--" + boundary + "\r\n";
    body += "Content-Disposition: form-data; name=\"file\"; filename=\"" + String(filename) + "\"\r\n";
    body += "Content-Type: application/octet-stream\r\n\r\n";

    WiFiClient client;
    if (!client.connect(SERVER_HOST, SERVER_PORT)) {
        LOG("[UPLOAD] Connection failed");
        file.close();
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

    client.print(headers);
    client.print(body);

    uint8_t buf[512];
    uint32_t totalSent = 0;
    while (file.available()) {
        int bytesRead = file.read(buf, sizeof(buf));
        if (bytesRead > 0) {
            client.write(buf, bytesRead);
            totalSent += bytesRead;
        }
    }
    file.close();

    client.print("\r\n--" + boundary + "--\r\n");

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
        LOG("[UPLOAD] Success: %s", filename);
        return true;
    } else {
        LOG("[UPLOAD] Failed: %s", response.substring(0, 100).c_str());
        return false;
    }
}

void uploadAllRecordings() {
    File root = SD.open("lifelog");
    if (!root) { LOG("[UPLOAD] Failed to open /lifelog"); return; }

    int uploaded = 0;
    File f = root.openNextFile();
    while (f) {
        if (String(f.name()).endsWith(".opus")) {
            char path[64];
            snprintf(path, sizeof(path), "/lifelog/%s", f.name());
            if (uploadFile(path)) {
                uploaded++;
                SD.remove(path);
                LOG("[UPLOAD] Deleted %s", path);
            }
        }
        f = root.openNextFile();
    }
    root.close();
    LOG("[UPLOAD] Done: %d files uploaded", uploaded);
}
