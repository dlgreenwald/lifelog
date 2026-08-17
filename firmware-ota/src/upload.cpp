#include "upload.h"
#include <WiFi.h>
#include <SD.h>
#include "config.h"
#include "audio.h"

bool uploadFile(const char* filename) {
    if (WiFi.status() != WL_CONNECTED) {
        LOG_UPLOAD(LOG_WARN, "No WiFi connection");
        return false;
    }

    sdBusy = true;
    File file = SD.open(filename, FILE_READ);
    if (!file) {
        sdBusy = false;
        LOG_UPLOAD(LOG_ERROR, "Failed to open %s", filename);
        return false;
    }

    uint32_t fileSize = file.size();
    LOG_UPLOAD(LOG_INFO, "Uploading %s (%d bytes)...", filename, fileSize);

    String url = String("http://") + SERVER_HOST + ":" + SERVER_PORT + SERVER_PATH;
    String boundary = "----LifeLogBoundary" + String(millis());
    String contentType = "multipart/form-data; boundary=" + boundary;

    String body = "";
    body += "--" + boundary + "\r\n";
    body += "Content-Disposition: form-data; name=\"file\"; filename=\"" + String(filename) + "\"\r\n";
    body += "Content-Type: application/octet-stream\r\n\r\n";

    WiFiClient client;
    if (!client.connect(SERVER_HOST, SERVER_PORT)) {
        LOG_UPLOAD(LOG_ERROR, "Connection failed");
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
    sdBusy = false;

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
        LOG_UPLOAD(LOG_INFO, "Success: %s", filename);
        return true;
    } else {
        LOG_UPLOAD(LOG_ERROR, "Failed: %s", response.substring(0, 100).c_str());
        return false;
    }
}

void uploadAllRecordings() {
    sdBusy = true;
    File root = SD.open("lifelog");
    if (!root) { LOG_UPLOAD(LOG_ERROR, "Failed to open /lifelog"); sdBusy = false; return; }

    int uploaded = 0;
    File f = root.openNextFile();
    while (f) {
        if (String(f.name()).endsWith(".opus")) {
            char path[64];
            snprintf(path, sizeof(path), "/lifelog/%s", f.name());
            if (uploadFile(path)) {
                uploaded++;
                SD.remove(path);
                LOG_UPLOAD(LOG_DEBUG, "Deleted %s", path);
            }
        }
        f = root.openNextFile();
    }
    root.close();
    sdBusy = false;
    LOG_UPLOAD(LOG_INFO, "Done: %d files uploaded", uploaded);
}
