#include "uploader.h"
#include "sd_storage.h"
#include "config.h"
#include <WiFi.h>
#include <HTTPClient.h>

extern QueueHandle_t opusQueue;
extern EventGroupHandle_t wifiEvent;

#define WIFI_CONNECTED_BIT BIT0

void uploaderTask(void *pvParameters) {
    Serial.println("[UPLOAD] Uploader task started");
    
    while (true) {
        // Wait for WiFi + data
        xEventGroupWaitBits(wifiEvent, WIFI_CONNECTED_BIT, false, true, portMAX_DELAY);
        
        OpusFrame frame;
        if (xQueueReceive(opusQueue, &frame, pdMS_TO_TICKS(100))) {
            if (!uploadAudio(frame)) {
                Serial.println("[UPLOAD] Failed, saving to SD");
                saveToSD(frame);
            }
        }
    }
}

bool uploadAudio(OpusFrame frame) {
    if (WiFi.status() != WL_CONNECTED) {
        return false;
    }
    
    HTTPClient http;
    
    // Build URL
    String url = "https://" + String(SERVER_HOST) + ":" + String(SERVER_PORT) + SERVER_PATH;
    
    http.begin(url);
    http.addHeader("Content-Type", "audio/opus");
    http.addHeader("X-API-Key", API_KEY);
    
    // Send Opus frame as binary data
    int httpResponseCode = http.POST(frame.data, frame.length);
    
    http.end();
    
    if (httpResponseCode == 200) {
        Serial.printf("[UPLOAD] Success (%d bytes)\n", frame.length);
        return true;
    } else {
        Serial.printf("[UPLOAD] Failed with code: %d\n", httpResponseCode);
        return false;
    }
}
