// Fixed-point AGC SUT + tests for native test environment.
// This file is included by test_all.cpp and provides both the test
// implementation and the SUT (agcInit / agcReset / agcProcessFrame).
// Mirrors the fixed-point AGC in src/i2s_fe.cpp.

#include <unity.h>
#include <cstring>
#include <cstdint>

// Fixed-point AGC (matches src/i2s_fe.cpp)
typedef struct {
    int32_t rms_q19;
    int32_t gain_q16;
} AgcState;

#define AGC_TARGET_RMS    4000
#define AGC_MIN_GAIN     16384
#define AGC_MAX_GAIN     262144
#define AGC_RMS_ALPHA_Q13 3277
#define AGC_GAIN_ALPHA_Q16 3277

static void agcReset(AgcState *s) {
    if (!s) return;
    s->rms_q19 = AGC_TARGET_RMS;
    s->gain_q16 = 65536;
}

static int agcInit(AgcState *s) {
    if (!s) return -1;
    s->rms_q19 = AGC_TARGET_RMS;
    s->gain_q16 = 65536;
    return 0;
}

// Integer sqrt: binary-search approximation
static int32_t isqrt(int32_t x) {
    if (x <= 0) return 0;
    int32_t lo = 0, hi = 1 << 16;
    while (lo + 1 < hi) {
        int32_t mid = (lo + hi) >> 1;
        int64_t mid_sq = (int64_t)mid * mid;
        if (mid_sq <= x) lo = mid;
        else hi = mid;
    }
    return lo;
}

static int agcProcessFrame(AgcState *s, int16_t *samples, int count) {
    if (!s || !samples || count <= 0) return -1;
    if (count != 512) return 0;

    int64_t sum_sq = 0;
    for (int i = 0; i < count; i++) {
        int32_t x = samples[i];
        sum_sq += (int64_t)x * x;
    }
    int32_t mean_sq_q19 = (int32_t)(sum_sq >> 9);
    int32_t rms_q19 = isqrt(mean_sq_q19);

    int32_t diff = rms_q19 - s->rms_q19;
    s->rms_q19 += (int32_t)(((int64_t)AGC_RMS_ALPHA_Q13 * diff + 4096) >> 13);

    int32_t rms = s->rms_q19 > 0 ? s->rms_q19 : 1;
    int64_t target_gain = ((int64_t)AGC_TARGET_RMS * 65536) / rms;
    if (target_gain < AGC_MIN_GAIN) target_gain = AGC_MIN_GAIN;
    if (target_gain > AGC_MAX_GAIN) target_gain = AGC_MAX_GAIN;

    int32_t gain_diff = (int32_t)target_gain - s->gain_q16;
    s->gain_q16 += (int32_t)(((int64_t)AGC_GAIN_ALPHA_Q16 * gain_diff + 32768) >> 16);

    int32_t g = s->gain_q16;
    for (int i = 0; i < count; i++) {
        int32_t x = samples[i];
        int64_t y = ((int64_t)x * g + 32768) >> 16;
        if (y > 32767) y = 32767;
        else if (y < -32768) y = -32768;
        samples[i] = (int16_t)y;
    }
    return 0;
}

// ── Tests ─────────────────────────────────────────────────────────

static void test_agcInit_returns_zero_and_sets_unity_gain() {
    AgcState s = {0};
    int result = agcInit(&s);
    TEST_ASSERT_EQUAL_INT(0, result);
    TEST_ASSERT_EQUAL_INT(AGC_TARGET_RMS, s.rms_q19);
    TEST_ASSERT_EQUAL_INT(65536, s.gain_q16);  // unity gain
}

static void test_agcInit_null_returns_error() {
    int result = agcInit(NULL);
    TEST_ASSERT_EQUAL_INT(-1, result);
}

static void test_agcReset_restores_defaults() {
    AgcState s = {999999, 999999};
    agcReset(&s);
    TEST_ASSERT_EQUAL_INT(AGC_TARGET_RMS, s.rms_q19);
    TEST_ASSERT_EQUAL_INT(65536, s.gain_q16);
}

static void test_agcProcessFrame_512_loud_signal_gets_reduced() {
    AgcState s = {0};
    agcInit(&s);
    int16_t frame[512];
    for (int i = 0; i < 512; i++) frame[i] = 16000;  // loud
    int result = agcProcessFrame(&s, frame, 512);
    TEST_ASSERT_EQUAL_INT(0, result);
    // Gain should be < unity (was loud, should be reduced)
    TEST_ASSERT_TRUE(s.gain_q16 < 65536);
}

static void test_agcProcessFrame_512_quiet_signal_gets_boosted() {
    AgcState s = {0};
    agcInit(&s);
    int16_t frame[512];
    for (int i = 0; i < 512; i++) frame[i] = 500;  // quiet
    int result = agcProcessFrame(&s, frame, 512);
    TEST_ASSERT_EQUAL_INT(0, result);
    // Gain should be > unity (was quiet, should be boosted)
    TEST_ASSERT_TRUE(s.gain_q16 > 65536);
    // But within max gain cap
    TEST_ASSERT_TRUE(s.gain_q16 <= AGC_MAX_GAIN);
}

static void test_agcProcessFrame_non512_passthrough() {
    AgcState s = {0};
    agcInit(&s);
    int16_t frame[128];
    for (int i = 0; i < 128; i++) frame[i] = 999;
    int result = agcProcessFrame(&s, frame, 128);
    TEST_ASSERT_EQUAL_INT(0, result);
    for (int i = 0; i < 128; i++) TEST_ASSERT_EQUAL_INT(999, frame[i]);
}

static void test_agcProcessFrame_zero_count_returns_error() {
    AgcState s = {0};
    agcInit(&s);
    int16_t frame[512] = {0};
    int result = agcProcessFrame(&s, frame, 0);
    TEST_ASSERT_EQUAL_INT(-1, result);
}

static void test_agcProcessFrame_null_samples_returns_error() {
    AgcState s = {0};
    agcInit(&s);
    int result = agcProcessFrame(&s, NULL, 512);
    TEST_ASSERT_EQUAL_INT(-1, result);
}

static void test_agcProcessFrame_partial_128_samples_passthrough() {
    AgcState s = {0};
    agcInit(&s);
    int16_t frame[128];
    for (int i = 0; i < 128; i++) frame[i] = 7777;
    int result = agcProcessFrame(&s, frame, 128);
    TEST_ASSERT_EQUAL_INT(0, result);
    // Non-512: passthrough, no gain applied
    for (int i = 0; i < 128; i++) TEST_ASSERT_EQUAL_INT(7777, frame[i]);
}
