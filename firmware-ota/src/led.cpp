// LED blink state machine — driven by audioActivity (set by VAD handler).
// Shares GPIO21 with SD CS: sdMutex non-blocking take inside ledLoop() makes
// SD operations naturally preempt the LED without priority inversion.

#include "audio.h"
#include "config.h"
#include "led.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static const char *TAG = "LED";
static unsigned long lastToggle = 0;
static bool ledOn = false;

void ledInit() {
    // LED_PIN already set OUTPUT in main.cpp setup()
}

void ledLoop() {
    unsigned long now = millis();

    // 100ms guard — 2× faster than RECORD's 250ms (fastest toggle interval) so we never
    // miss a latest toggle. Spinning burn is negligible; mutex contention is the real cost.
    if (now - lastToggle < 100) return;

    // Non-blocking mutex take: SD ops holding the mutex block us, preempting LED.
    if (xSemaphoreTakeRecursive(sdMutex, pdMS_TO_TICKS(0)) != pdTRUE) return;

    if (audioActivity == AUDIO_IDLE) {
        // Solid off — drive low once, then skip ticks.
        if (ledOn) {
            digitalWrite(LED_PIN, LOW);
            ledOn = false;
        }
        lastToggle = now;
    } else if (audioActivity == AUDIO_LISTEN) {
        // Slow blink — full cycle 1000ms (500ms on, 500ms off, i.e. 1 Hz).
        // Auto-promote to RECORD after 2 seconds of continuous voice.
        if (now - listenStartMs > 2000) {
            audioActivity = AUDIO_RECORD;
            // Reset cadence so the freshly-entered RECORD state doesn't try to fire
            // an immediate toggle against a stale lastToggle baseline from LISTEN.
            lastToggle = now;
        } else if (now - lastToggle >= 500) {
            digitalWrite(LED_PIN, ledOn ? LOW : HIGH);
            ledOn = !ledOn;
            lastToggle = now;
        }
    } else if (audioActivity == AUDIO_RECORD) {
        // Fast blink — full cycle 500ms (250ms on, 250ms off, i.e. 2 Hz).
        if (now - lastToggle >= 250) {
            digitalWrite(LED_PIN, ledOn ? LOW : HIGH);
            ledOn = !ledOn;
            lastToggle = now;
        }
    }

    xSemaphoreGiveRecursive(sdMutex);
}
