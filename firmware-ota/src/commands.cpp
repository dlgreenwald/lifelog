#include "commands.h"
#include "config.h"
#include "audio.h"
#include "upload.h"
#include <SD.h>
#include <I2S.h>

void commandsInit() {
    // Commands read from Serial in loop
}

void processCommand() {
    if (!Serial.available()) return;
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "rec") {
        if (vadMode) {
            LOG_VAD(LOG_INFO, "Listening... (speak to record, silence saves)");
            recording = true;
        } else {
            startRecording(5000);
        }
    } else if (cmd == "stop") {
        recording = false;
        LOG_AUDIO(LOG_INFO, "Stopped");
    } else if (cmd == "vad") {
        toggleVAD();
    } else if (cmd == "upload") {
        LOG_UPLOAD(LOG_INFO, "Starting upload of all recordings...");
        uploadAllRecordings();
    } else if (cmd == "ls") {
        File root = SD.open("lifelog");
        if (root) {
            File f = root.openNextFile();
            while (f) { LOG_LS(LOG_DEBUG, "%s %d bytes", f.name(), f.size()); f = root.openNextFile(); }
            root.close();
        }
    } else if (cmd == "mic") {
        LOG_MIC(LOG_INFO, "Starting mic test - reading for 5 seconds...");
        int16_t buffer[480];
        uint32_t startMs = millis();
        uint32_t sumRms = 0;
        uint32_t count = 0;
        uint32_t maxRms = 0;
        while (millis() - startMs < 5000) {
            int sample = I2S.read();
            if (sample > 1 || sample < -1) {
                float rms = abs(sample);
                sumRms += (uint32_t)rms;
                count++;
                if (rms > maxRms) maxRms = (uint32_t)rms;
            }
        }
        float avgRms = (count > 0) ? (float)sumRms / count : 0;
        LOG_MIC(LOG_INFO, "Test: avg=%.1f, max=%lu, samples=%lu", avgRms, maxRms, count);
        LOG_MIC(LOG_WARN, "If avg < 10, mic may not be connected");
    } else if (cmd.length() > 0) {
        LOG_CMD(LOG_WARN, "Unknown: %s", cmd.c_str());
    }
}
