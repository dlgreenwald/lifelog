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
        File root = SD.open("/lifelog");
        if (root) {
            File f = root.openNextFile();
            while (f) { LOG("[LS] %s %d bytes", f.name(), f.size()); f = root.openNextFile(); }
            root.close();
        }
    } else {
        LOG("[CMD] Unknown: %s", cmd.c_str());
    }
}
