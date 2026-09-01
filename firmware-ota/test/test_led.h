// LED blink state machine tests — pure-logic; pulls in led.cpp + defines
// the audio/sd globals it references (no need to drag in the full audio.cpp
// translation unit which depends on FreeRTOS/esp-sr/PSRAM).

#include <unity.h>
#include "mocks.h"

// Provide the symbols led.cpp expects. Definitions, not externs,
// because audio.cpp is NOT pulled into this TU.
#include "audio.h"  // for AudioActivity enum
#include "config.h"  // for LED_PIN (mocks skips)
volatile AudioActivity audioActivity = AUDIO_IDLE;
unsigned long listenStartMs = 0;
volatile bool recording = false;
volatile bool vadMode = true;
volatile uint32_t utteranceId = 0;
volatile uint32_t chunkIndex = 0;
volatile bool isFinal = false;
SemaphoreHandle_t sdMutex = (SemaphoreHandle_t)0xA;  // arbitrary non-null handle

#include "led.cpp"
// Per-test reset (host main()'s setUp() in test_all.cpp calls this).
extern "C" void reset_led_state() {
    audioActivity = AUDIO_IDLE;
    listenStartMs = 0;
    lastToggle = 0;
    ledOn = false;
    mock_digital_write_calls.clear();
    mock_digital_write_pin = -1;
    mock_digital_write_val = -1;
    mock_millis_value = 10000;
}

// Each test calls reset_led_state() first — setUp() analog.

// ── AudioActivity transitions ────────────────────────────────────

void test_audio_activity_listen_turns_led_on(void) {
    reset_led_state();
    audioActivity = AUDIO_LISTEN;
    listenStartMs = mock_millis_value;
    ledLoop();
    TEST_ASSERT_EQUAL(21, mock_digital_write_pin);
    TEST_ASSERT_EQUAL(1, (int)mock_digital_write_calls.size());
    TEST_ASSERT_EQUAL(HIGH, mock_digital_write_val);
}

void test_audio_activity_idle_turns_led_off(void) {
    reset_led_state();
    audioActivity = AUDIO_IDLE;
    ledOn = true;
    ledLoop();
    TEST_ASSERT_EQUAL(21, mock_digital_write_pin);
    TEST_ASSERT_EQUAL(LOW, mock_digital_write_val);
}

void test_listen_blinks_1hz(void) {
    reset_led_state();
    audioActivity = AUDIO_LISTEN;
    listenStartMs = mock_millis_value;  // t=10000

    // Tick at t=10000 — first 100ms guard passes (10000-0>=100), and
    // now-listenStartMs=0 NOT > 2000 → still LISTEN, so toggle ON
    ledLoop();
    TEST_ASSERT_EQUAL(HIGH, mock_digital_write_val);

    // LISTEN toggle interval = 500ms (1000ms full cycle at 1 Hz)
    mock_millis_value += 500;
    ledLoop();
    TEST_ASSERT_EQUAL(LOW, mock_digital_write_val);   // OFF half-cycle

    // Advance to t=11000 — still within 2s listen window
    mock_millis_value += 500;
    ledLoop();
    TEST_ASSERT_EQUAL(HIGH, mock_digital_write_val);  // ON half-cycle
}

void test_record_blinks_2hz(void) {
    reset_led_state();
    audioActivity = AUDIO_RECORD;
    ledLoop();
    TEST_ASSERT_EQUAL(HIGH, mock_digital_write_val);
    // RECORD toggle interval = 250ms (500ms full cycle at 2 Hz)
    mock_millis_value += 250;
    ledLoop();
    TEST_ASSERT_EQUAL(LOW, mock_digital_write_val);
    mock_millis_value += 250;
    ledLoop();
    TEST_ASSERT_EQUAL(HIGH, mock_digital_write_val);
}

void test_idle_skips_toggle_when_already_off(void) {
    reset_led_state();
    audioActivity = AUDIO_IDLE;
    ledOn = false;
    mock_digital_write_calls.clear();
    ledLoop();
    TEST_ASSERT_EQUAL(0, (int)mock_digital_write_calls.size());
}

void test_listen_transitions_to_record_after_2000ms(void) {
    reset_led_state();
    audioActivity = AUDIO_LISTEN;
    listenStartMs = mock_millis_value;  // t=10000
    ledLoop();  // toggle ON, lastToggle=10000, ledOn=true

    // Push past 2000ms — auto-promote to RECORD happens in the LISTEN branch.
    // lastToggle reset to now inside ledLoop so the *next* cycle is on the
    // fresh cadence (no stale toggle on the same call).
    mock_millis_value += 2001;
    mock_digital_write_calls.clear();
    ledLoop();
    TEST_ASSERT_EQUAL(AUDIO_RECORD, audioActivity);
    TEST_ASSERT_EQUAL(0, (int)mock_digital_write_calls.size());

    // Advance 250ms within RECORD → first toggle fires (off, ledOn was true).
    mock_millis_value += 250;
    ledLoop();
    TEST_ASSERT_EQUAL(1, (int)mock_digital_write_calls.size());
    TEST_ASSERT_EQUAL(LOW, mock_digital_write_val);
}


void test_voice_restart_resets_listen_timer(void) {
    reset_led_state();
    audioActivity = AUDIO_LISTEN;
    mock_millis_value += 1500;
    // VAD restarts: i2s_fe.cpp would set listenStartMs again
    listenStartMs = mock_millis_value;  // t=11500
    mock_millis_value += 500;            // t=12000 — 500ms since restart
    mock_digital_write_calls.clear();
    ledLoop();

    // now-listenStartMs = 500, NOT > 2000 → still LISTEN
    TEST_ASSERT_EQUAL(AUDIO_LISTEN, audioActivity);
}

void test_100ms_guard_skips_rapid_calls(void) {
    reset_led_state();
    audioActivity = AUDIO_LISTEN;
    listenStartMs = mock_millis_value;
    ledLoop();  // consumes the guard slot (sets lastToggle=10000)
    int countAfterFirst = (int)mock_digital_write_calls.size();

    // No time advance — 100ms guard blocks the second invocation.
    ledLoop();
    TEST_ASSERT_EQUAL(countAfterFirst, (int)mock_digital_write_calls.size());
}

void test_idle_after_listen_clears_immediately(void) {
    reset_led_state();
    // ledLoop on the IDLE branch drives the LED off on the same cycle.
    audioActivity = AUDIO_IDLE;
    ledOn = true;
    ledLoop();
    TEST_ASSERT_EQUAL(LOW, mock_digital_write_val);
}
