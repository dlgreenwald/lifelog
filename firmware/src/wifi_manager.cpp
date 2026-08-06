#include "wifi_manager.h"
#include "sd_storage.h"
#include "config.h"
#include <WiFi.h>

extern EventGroupHandle_t wifiEvent;

#define WIFI_CONNECTED_BIT BIT0
#define SD_FLUSH_BIT BIT1

void wifiManagerTask(void *pvParameters) {
    uint32_t reconnectDelay = 1000;
    
    Serial.printf("[WIFI] Connecting to %s\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    while (true) {
        if (WiFi.status() != WL_CONNECTED) {
            xEventGroupClearBits(wifiEvent, WIFI_CONNECTED_BIT);
            Serial.printf("[WIFI] Disconnected (status=%d)\n", WiFi.status());
            vTaskDelay(pdMS_TO_TICKS(reconnectDelay));
            reconnectDelay = (reconnectDelay * 2 > 30000) ? 30000 : reconnectDelay * 2;
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            Serial.printf("[WIFI] Reconnecting (delay: %lu ms)\n", reconnectDelay);
        } else {
            reconnectDelay = 1000;  // Reset on success
            xEventGroupSetBits(wifiEvent, WIFI_CONNECTED_BIT);
            
            static bool firstConnect = true;
            if (firstConnect) {
                Serial.printf("[WIFI] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
                firstConnect = false;
            }
            
            // Flush SD queue on reconnect
            if (sdHasPendingFiles()) {
                Serial.println("[WIFI] Flushing SD queue...");
                flushSDQueue();
            }
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

bool isWiFiConnected() {
    return WiFi.status() == WL_CONNECTED;
}
