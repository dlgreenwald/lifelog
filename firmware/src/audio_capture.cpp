#include "audio_capture.h"
#include "config.h"
#include <driver/i2s.h>
#include <math.h>

extern QueueHandle_t pcmQueue;
extern volatile bool recording;

void audioCaptureTask(void *pvParameters) {
    int16_t buffer[PCM_BUFFER_SIZE];  // 30ms at 16kHz
    bool voiceActive = false;
    uint32_t silenceMs = 0;
    
    Serial.printf("[AUDIO] Capture task started (buf=%d samples)\n", PCM_BUFFER_SIZE);
    
    while (true) {
        if (!recording) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        
        size_t bytesRead = 0;
        esp_err_t err = i2s_read(I2S_NUM_0, buffer, sizeof(buffer), &bytesRead, pdMS_TO_TICKS(100));
        
        if (err != ESP_OK) {
            Serial.printf("[AUDIO] I2S read error: %d\n", err);
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (bytesRead == 0) {
            continue;
        }
        
        // VAD: compute RMS
        int sampleCount = bytesRead / 2;
        float rms = computeRMS(buffer, sampleCount);
        
        if (rms > VAD_THRESHOLD) {
            if (!voiceActive) {
                Serial.printf("[VAD] Voice started (RMS=%.0f)\n", rms);
            }
            voiceActive = true;
            silenceMs = 0;
            
            AudioChunk chunk;
            memcpy(chunk.data, buffer, bytesRead);
            chunk.length = bytesRead;
            if (xQueueSend(pcmQueue, &chunk, pdMS_TO_TICKS(50)) != pdTRUE) {
                Serial.println("[AUDIO] PCM queue full, dropping chunk");
            }
            
        } else if (voiceActive) {
            silenceMs += 30;
            
            if (silenceMs > 1500) {  // 1.5s silence = end of utterance
                voiceActive = false;
                // Send end-of-utterance marker
                AudioChunk endMarker = { .length = 0 };
                xQueueSend(pcmQueue, &endMarker, pdMS_TO_TICKS(50));
                Serial.println("[VAD] End of utterance detected");
            }
        }
    }
}

float computeRMS(int16_t *samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}
