#include "ota_manager.h"
#include <WiFi.h>
#include <WebServer.h>
#include <Update.h>
#include <Preferences.h>
#include <esp_ota_ops.h>

static WebServer otaServer(OTA_SERVER_PORT);
static Preferences prefs;
static esp_ota_handle_t otaHandle = 0;
static const esp_partition_t* otaPartition = NULL;
static bool firmwareConfirmed = false;
static int bootAttempts = 0;

// NVS keys
static const char* NVS_NAMESPACE = "lifelog_ota";
static const char* KEY_BOOT_COUNT = "boot_count";
static const char* KEY_CONFIRMED = "confirmed";

// Handle OTA firmware upload
static void handleOtaUpdate() {
    HTTPUpload& upload = otaServer.upload();
    
    if (upload.status == UPLOAD_FILE_START) {
        Serial.printf("[OTA] Update start: %s\n", upload.filename.c_str());
        
        // Get next OTA partition
        otaPartition = esp_ota_get_next_update_partition(NULL);
        if (!otaPartition) {
            Serial.println("[OTA] ERROR: No OTA partition found");
            return;
        }
        Serial.printf("[OTA] Target partition: %s (addr=0x%06X, size=%d)\n",
                      otaPartition->label, otaPartition->address, otaPartition->size);
        
        // Start OTA
        esp_err_t err = esp_ota_begin(otaPartition, OTA_SIZE_UNKNOWN, &otaHandle);
        if (err != ESP_OK) {
            Serial.printf("[OTA] esp_ota_begin failed: %d\n", err);
            return;
        }
        
    } else if (upload.status == UPLOAD_FILE_WRITE) {
        // Write chunk to OTA
        esp_err_t err = esp_ota_write(otaHandle, upload.buf, upload.currentSize);
        if (err != ESP_OK) {
            Serial.printf("[OTA] esp_ota_write failed: %d\n", err);
            return;
        }
        Serial.printf("[OTA] Written %d bytes (%d/%d)\n", 
                      upload.currentSize, upload.totalSize, upload.totalSize);
        
    } else if (upload.status == UPLOAD_FILE_END) {
        // Finish OTA
        esp_err_t err = esp_ota_end(otaHandle);
        if (err != ESP_OK) {
            Serial.printf("[OTA] esp_ota_end failed: %d\n", err);
            return;
        }
        
        Serial.printf("[OTA] Update complete: %d bytes\n", upload.totalSize);
        
        // Mark as unconfirmed (will be confirmed after successful boot)
        prefs.begin(NVS_NAMESPACE, false);
        prefs.putUInt(KEY_CONFIRMED, 0);
        prefs.putUInt(KEY_BOOT_COUNT, 0);
        prefs.end();
        
        // Set boot partition to new firmware
        err = esp_ota_set_boot_partition(otaPartition);
        if (err != ESP_OK) {
            Serial.printf("[OTA] esp_ota_set_boot_partition failed: %d\n", err);
            return;
        }
        
        Serial.println("[OTA] Rebooting in 1 second...");
        delay(1000);
        ESP.restart();
    }
}

// Handle OTA upload status page
static void handleOtaRoot() {
    String html = "<!DOCTYPE html><html><head><title>LifeLog OTA</title></head>";
    html += "<body><h1>LifeLog Firmware Update</h1>";
    html += "<p>Current slot: " + String(otaGetCurrentSlot()) + "</p>";
    html += "<p>Boot attempts: " + String(bootAttempts) + "/" + String(OTA_MAX_BOOT_ATTEMPTS) + "</p>";
    html += "<form method='POST' action='/update' enctype='multipart/form-data'>";
    html += "<input type='file' name='firmware'><br><br>";
    html += "<input type='submit' value='Update Firmware'>";
    html += "</form>";
    html += "<hr><p><a href='/reboot'>Reboot Device</a> | <a href='/rollback'>Rollback to Previous Firmware</a></p>";
    html += "</body></html>";
    otaServer.send(200, "text/html", html);
}

// Handle reboot request
static void handleReboot() {
    otaServer.send(200, "text/plain", "Rebooting...");
    delay(1000);
    ESP.restart();
}

// Handle rollback request - switch to the other OTA slot
static void handleRollback() {
    Serial.println("[OTA] Rollback requested");
    const esp_partition_t* current = esp_ota_get_running_partition();
    if (!current) {
        otaServer.send(500, "text/plain", "Cannot determine current partition");
        return;
    }

    // Try both OTA subtypes, pick the one that isn't current
    const esp_partition_t* target = NULL;
    for (int sub = ESP_PARTITION_SUBTYPE_APP_OTA_0; sub <= ESP_PARTITION_SUBTYPE_APP_OTA_1; sub++) {
        esp_partition_iterator_t it = esp_partition_find(ESP_PARTITION_TYPE_APP, (esp_partition_subtype_t)sub, NULL);
        if (it) {
            const esp_partition_t* p = esp_partition_get(it);
            if (p && strcmp(p->label, current->label) != 0) {
                target = p;
            }
            esp_partition_iterator_release(it);
            if (target) break;
        }
    }

    if (target) {
        Serial.printf("[OTA] Rolling back from %s to %s\n", current->label, target->label);
        esp_ota_set_boot_partition(target);
        delay(1000);
        ESP.restart();
    } else {
        otaServer.send(500, "text/plain", "Other OTA partition not found");
    }
}

// Handle update status
static void handleOtaStatus() {
    String status = Update.hasError() ? "ERROR" : "OK";
    otaServer.send(200, "application/json", "{\"status\":\"" + status + "\"}");
}

void otaManagerInit() {
    // Initialize NVS
    prefs.begin(NVS_NAMESPACE, false);
    
    // Check if this is first boot after OTA
    firmwareConfirmed = prefs.getUInt(KEY_CONFIRMED, 0) == 1;
    bootAttempts = prefs.getUInt(KEY_BOOT_COUNT, 0);
    
    if (firmwareConfirmed) {
        Serial.println("[OTA] Firmware confirmed");
    } else {
        bootAttempts++;
        Serial.printf("[OTA] Boot attempt %d/%d (not confirmed)\n", 
                      bootAttempts, OTA_MAX_BOOT_ATTEMPTS);
        
        // Save boot count
        prefs.putUInt(KEY_BOOT_COUNT, bootAttempts);
        
        // Check if we've exceeded max attempts
        if (bootAttempts >= OTA_MAX_BOOT_ATTEMPTS) {
            Serial.println("[OTA] WARNING: Max boot attempts reached!");
            Serial.println("[OTA] Firmware not confirmed - consider rollback");
            // Note: We don't auto-rollback here, but log the warning
            // User can manually rollback or fix the firmware
        }
    }
    
    prefs.end();
}

void otaServerStart() {
    // Configure OTA routes
    otaServer.on("/", HTTP_GET, handleOtaRoot);
    otaServer.on("/update", HTTP_POST, handleOtaStatus, handleOtaUpdate);
    otaServer.on("/reboot", HTTP_GET, handleReboot);
    otaServer.on("/rollback", HTTP_GET, handleRollback);
    otaServer.begin();
    
    Serial.printf("[OTA] Server started on port %d\n", OTA_SERVER_PORT);
    Serial.println("[OTA] Access http://<device-ip>:8080/ for firmware update");
}

void otaConfirmFirmware() {
    if (!firmwareConfirmed) {
        prefs.begin(NVS_NAMESPACE, false);
        prefs.putUInt(KEY_CONFIRMED, 1);
        prefs.putUInt(KEY_BOOT_COUNT, 0);
        prefs.end();
        firmwareConfirmed = true;
        Serial.println("[OTA] Firmware confirmed after successful boot");
    }
}

int otaGetCurrentSlot() {
    const esp_partition_t* current = esp_ota_get_running_partition();
    if (current) {
        // Check if it's ota_0 or ota_1
        if (strcmp(current->label, "app0") == 0) return 0;
        if (strcmp(current->label, "app1") == 0) return 1;
    }
    return -1;
}

int otaGetBootAttempts() {
    return bootAttempts;
}

// Call this in loop() to handle OTA server requests
void otaServerHandleClient() {
    otaServer.handleClient();
}
