#include "opus_encoder.h"
#include "config.h"
#include <string.h>

extern QueueHandle_t pcmQueue;
extern QueueHandle_t opusQueue;

void opusEncodeTask(void *pvParameters) {
    // Create Opus encoder
    OpusEncoder *encoder = opus_encoder_create(
        SAMPLE_RATE, 1, 
        OPUS_APPLICATION_RESTRICTED_LOWDELAY, NULL
    );
    
    if (!encoder) {
        Serial.println("[OPUS] Encoder creation failed");
        vTaskDelete(NULL);
        return;
    }
    
    opus_encoder_ctl(encoder, OPUS_SET_BITRATE(OPUS_BITRATE));
    opus_encoder_ctl(encoder, OPUS_SET_COMPLEXITY(5));
    
    Serial.println("[OPUS] Encoder initialized");
    
    uint8_t opusBuffer[1024];
    int16_t pcmBuffer[OPUS_FRAME_SIZE];  // 60ms at 16kHz = 960 samples
    int pcmIndex = 0;
    
    while (true) {
        AudioChunk chunk;
        xQueueReceive(pcmQueue, &chunk, portMAX_DELAY);
        
        // End-of-utterance marker: flush remaining PCM
        if (chunk.length == 0) {
            if (pcmIndex > 0) {
                // Pad remaining buffer with zeros
                memset(pcmBuffer + pcmIndex, 0, (OPUS_FRAME_SIZE - pcmIndex) * sizeof(int16_t));
                pcmIndex = OPUS_FRAME_SIZE;
                
                int bytesEncoded = opus_encode(encoder, pcmBuffer, pcmIndex, 
                    opusBuffer, sizeof(opusBuffer));
                if (bytesEncoded > 0) {
                    OpusFrame frame;
                    memcpy(frame.data, opusBuffer, bytesEncoded);
                    frame.length = bytesEncoded;
                    xQueueSend(opusQueue, &frame, portMAX_DELAY);
                }
                pcmIndex = 0;
            }
            continue;
        }
        
        // Accumulate PCM until 960 samples (60ms), then encode
        int samplesToAdd = chunk.length / 2;  // bytes to 16-bit samples
        int samplesAvailable = OPUS_FRAME_SIZE - pcmIndex;
        int samplesToCopy = (samplesToAdd < samplesAvailable) ? samplesToAdd : samplesAvailable;
        
        memcpy(pcmBuffer + pcmIndex, chunk.data, samplesToCopy * sizeof(int16_t));
        pcmIndex += samplesToCopy;
        
        if (pcmIndex >= OPUS_FRAME_SIZE) {
            int bytesEncoded = opus_encode(encoder, pcmBuffer, OPUS_FRAME_SIZE, 
                opusBuffer, sizeof(opusBuffer));
            if (bytesEncoded > 0) {
                OpusFrame frame;
                memcpy(frame.data, opusBuffer, bytesEncoded);
                frame.length = bytesEncoded;
                xQueueSend(opusQueue, &frame, portMAX_DELAY);
            }
            pcmIndex = 0;
        }
    }
}
