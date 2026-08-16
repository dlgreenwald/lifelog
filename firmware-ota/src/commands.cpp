#include "commands.h"
#include "config.h"
#include "audio.h"
#include "upload.h"
#include <SD.h>

extern RemoteDebug Debug;

void commandsInit() {
    Debug.setCallBackProjectCmds(processCommand);
    Debug.setHelpProjectsCmds("rec - start recording\nstop - stop\nls - list files\nupload - upload to server\nvad - toggle VAD mode");
}

void processCommand() {
    String cmd = Debug.getLastCommand();
    cmd.trim();
    if (cmd == "rec") {
        if (vadMode) {
            LOG("[VAD] Listening... (speak to record, silence saves)");
            recording = true;
        } else {
            startRecording(5000);
        }
    } else if (cmd == "stop") {
        recording = false;
        LOG("[AUDIO] Stopped");
    } else if (cmd == "vad") {
        toggleVAD();
    } else if (cmd == "upload") {
        LOG("[UPLOAD] Starting upload of all recordings...");
        uploadAllRecordings();
    } else if (cmd == "ls") {
        File root = SD.open("lifelog");
        if (root) {
            File f = root.openNextFile();
            while (f) { LOG("[LS] %s %d bytes", f.name(), f.size()); f = root.openNextFile(); }
            root.close();
        }
    } else if (cmd == "mic") {
        LOG("[MIC] Starting mic test - reading for 5 seconds...");
        int16_t buffer[480];
        uint32_t startMs = millis();
        uint32_t sumRms = 0;
        uint32_t count = 0;
        uint32_t maxRms = 0;
        while (millis() - startMs < 5000) {
            size_t bytesRead = 0;
            i2s_read(I2S_NUM_0, buffer, sizeof(buffer), &bytesRead, pdMS_TO_TICKS(100));
            if (bytesRead > 0) {
                float sum = 0;
                for (int i = 0; i < bytesRead/2; i++) sum += (float)buffer[i] * (float)buffer[i];
                float rms = sqrtf(sum / (bytesRead/2));
                sumRms += (uint32_t)rms;
                count++;
                if (rms > maxRms) maxRms = (uint32_t)rms;
            }
        }
        float avgRms = (count > 0) ? (float)sumRms / count : 0;
        LOG("[MIC] Test: avg=%.1f, max=%lu, samples=%lu", avgRms, maxRms, count);
        LOG("[MIC] If avg < 10, mic may not be connected");
    } else {
        LOG("[CMD] Unknown: %s", cmd.c_str());
    }
}
