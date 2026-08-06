#include "battery.h"
#include "config.h"

extern volatile bool recording;

void batteryMonitorTask(void *pvParameters) {
    uint32_t lastBlink = 0;
    bool ledState = false;
    
    Serial.println("[BATT] Monitor task started");
    
    while (true) {
        float voltage = readBatteryVoltage();
        int percent = voltageToPercent(voltage);
        
        // Blink LED at 1Hz when battery < 10%
        if (percent <= 10) {
            uint32_t now = millis();
            if (now - lastBlink >= 1000) {
                ledState = !ledState;
                digitalWrite(LED_BLUE_PIN, ledState);
                lastBlink = now;
            }
        } else {
            digitalWrite(LED_BLUE_PIN, LOW);
        }
        
        // Log battery status periodically (every 30 seconds)
        static uint32_t lastLog = 0;
        uint32_t now = millis();
        if (now - lastLog >= 30000) {
            Serial.printf("[BATT] Voltage: %.2fV (%d%%)\n", voltage, percent);
            lastLog = now;
        }
        
        // Critical voltage: graceful shutdown
        if (voltage < BATTERY_CRITICAL_VOLTAGE) {
            Serial.println("[BATT] CRITICAL - Shutting down");
            recording = false;
            // Wait for current upload to finish
            vTaskDelay(pdMS_TO_TICKS(5000));
            esp_deep_sleep_start();
        }
        
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

float readBatteryVoltage() {
    int raw = analogRead(BATTERY_ADC_PIN);
    // XIAO uses voltage divider - adjust for your board
    return (raw / 4095.0) * 2 * 3.3;
}

int voltageToPercent(float voltage) {
    if (voltage >= 4.1) return 100;
    if (voltage >= 3.8) return 70;
    if (voltage >= 3.6) return 50;
    if (voltage >= 3.4) return 30;
    if (voltage >= 3.3) return 10;
    if (voltage >= 3.0) return 5;
    return 0;
}
