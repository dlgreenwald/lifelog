#include "sd_storage.h"
#include "config.h"
#include <SPI.h>
#include <SD.h>

extern SemaphoreHandle_t sdMutex;

static uint32_t chunkCounter = 0;

void initSDStorage() {
    // SD card is initialized in main.cpp
    Serial.println("[SD] Storage module ready");
}

static String getTimestamp() {
    // Simple timestamp based on millis for file naming
    unsigned long ms = millis();
    unsigned long seconds = ms / 1000;
    unsigned long minutes = seconds / 60;
    unsigned long hours = minutes / 60;
    
    char buf[16];
    snprintf(buf, sizeof(buf), "%02lu%02lu%02lu",
             hours % 24, minutes % 60, seconds % 60);
    return String(buf);
}

void saveToSD(OpusFrame frame) {
    xSemaphoreTake(sdMutex, portMAX_DELAY);
    
    char filename[64];
    snprintf(filename, sizeof(filename), "/lifelog/%s_%04lu.opus", 
        getTimestamp().c_str(), chunkCounter++);
    
    File file = SD.open(filename, FILE_WRITE);
    if (file) {
        file.write(frame.data, frame.length);
        file.close();
        Serial.printf("[SD] Saved: %s (%d bytes)\n", filename, frame.length);
    } else {
        Serial.printf("[SD] Failed to open: %s\n", filename);
    }
    
    xSemaphoreGive(sdMutex);
}

void flushSDQueue() {
    File root = SD.open("/lifelog");
    if (!root) {
        Serial.println("[SD] Failed to open /lifelog");
        return;
    }
    
    int filesUploaded = 0;
    while (File file = root.openNextFile()) {
        String filePath = String(file.name());
        file.close();
        
        // Try to upload file
        // In real implementation, this would read and upload via uploader
        Serial.printf("[SD] Flushing: %s\n", filePath.c_str());
        
        // Remove after successful upload
        SD.remove(filePath.c_str());
        filesUploaded++;
    }
    
    root.close();
    Serial.printf("[SD] Flushed %d files\n", filesUploaded);
}

bool sdHasPendingFiles() {
    File root = SD.open("/lifelog");
    if (!root) return false;
    
    bool hasFiles = false;
    while (File file = root.openNextFile()) {
        hasFiles = true;
        file.close();
        break;
    }
    root.close();
    return hasFiles;
}
