// AGC fixed-point signal-processing tests — pure-logic; pulls in the AGC
// functions and AgcState struct directly so tests can inspect internal state.

#include <unity.h>
#include <cstdint>
#include <cstring>

// ── AgcState and AGC functions (copied from i2s_fe.cpp) ──────────

typedef struct {
    int32_t rms_q19;      // Q19.13 EMA of RMS × 8192
    int32_t gain_q16;     // Q16.16 current gain multiplier
} AgcState;

#define AGC_TARGET_RMS    2000
#define AGC_MIN_GAIN      16384
#define AGC_MAX_GAIN      2097152
#define AGC_RMS_ALPHA_Q13 3277
#define AGC_GAIN_ALPHA_Q16 3277

static void agcReset(AgcState *s) {
    if (!s) return;
    s->rms_q19 = AGC_TARGET_RMS;
    s->gain_q16 = 65536;  // unity gain
}

static int agcInit(AgcState *s) {
    if (!s) return -1;
    s->rms_q19 = AGC_TARGET_RMS;
    s->gain_q16 = 65536;
    return 0;
}

static inline int32_t mul_q16(int32_t a, int32_t b) {
    return (int32_t)((((int64_t)a * b) + 32768) >> 16);
}

static int32_t agcProcessFrame(AgcState *s, int16_t *samples, int count) {
    if (!s || !samples || count <= 0) return -1;
    if (count != 512) return 0;

    int64_t sum_sq = 0;
    for (int i = 0; i < count; i++) {
        int32_t x = samples[i];
        sum_sq += (int64_t)x * x;
    }
    int32_t mean_sq_q19 = (int32_t)(sum_sq >> 9);
    int32_t rms_q19 = 0;
    if (mean_sq_q19 > 0) {
        int32_t hi = 1 << 16;
        int32_t lo = 0;
        while (lo + 1 < hi) {
            int32_t mid = (lo + hi) >> 1;
            int64_t mid_sq = (int64_t)mid * mid;
            if (mid_sq <= mean_sq_q19) lo = mid;
            else hi = mid;
        }
        rms_q19 = lo;
    }

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

// ── Helpers ──────────────────────────────────────────────────────

static void fill_sine(int16_t *buf, int count, int16_t amplitude) {
    for (int i = 0; i < count; i++) {
        buf[i] = (int16_t)(amplitude);
    }
}

// ── Tests ─────────────────────────────────────────────────────────

void test_agcInit_returns_zero_and_sets_unity_gain(void) {
    AgcState s = {0};
    TEST_ASSERT_EQUAL_INT(0, agcInit(&s));
    TEST_ASSERT_EQUAL_INT(AGC_TARGET_RMS, s.rms_q19);
    TEST_ASSERT_EQUAL_INT(65536, s.gain_q16);  // unity
}

void test_agcInit_null_returns_error(void) {
    TEST_ASSERT_EQUAL_INT(-1, agcInit(NULL));
}

void test_agcReset_restores_defaults(void) {
    AgcState s = {999999, 999999};
    agcReset(&s);
    TEST_ASSERT_EQUAL_INT(AGC_TARGET_RMS, s.rms_q19);
    TEST_ASSERT_EQUAL_INT(65536, s.gain_q16);
}

void test_agcProcessFrame_512_loud_signal_gets_reduced(void) {
    AgcState s = {AGC_TARGET_RMS, 65536};
    int16_t samples[512];
    // Loud signal: RMS >> target → gain should be < 65536 (attenuated)
    fill_sine(samples, 512, 20000);
    agcProcessFrame(&s, samples, 512);
    // Gain should have been reduced from unity
    TEST_ASSERT_TRUE(s.gain_q16 < 65536);
}

void test_agcProcessFrame_512_quiet_signal_gets_boosted(void) {
    AgcState s = {AGC_TARGET_RMS, 65536};
    int16_t samples[512];
    // Quiet signal: RMS << target → gain should be > 65536 (boosted)
    fill_sine(samples, 512, 100);
    agcProcessFrame(&s, samples, 512);
    // Gain should have been boosted above unity
    TEST_ASSERT_TRUE(s.gain_q16 > 65536);
}

void test_agcProcessFrame_non512_passthrough(void) {
    AgcState s = {AGC_TARGET_RMS, 65536};
    int16_t samples[128];
    fill_sine(samples, 128, 1000);
    // Returns 0 for non-512 counts, gain unchanged
    TEST_ASSERT_EQUAL_INT(0, agcProcessFrame(&s, samples, 128));
    TEST_ASSERT_EQUAL_INT(65536, s.gain_q16);
}

void test_agcProcessFrame_zero_count_returns_error(void) {
    AgcState s = {AGC_TARGET_RMS, 65536};
    int16_t samples[512] = {0};
    TEST_ASSERT_EQUAL_INT(-1, agcProcessFrame(&s, samples, 0));
}

void test_agcProcessFrame_null_samples_returns_error(void) {
    AgcState s = {AGC_TARGET_RMS, 65536};
    TEST_ASSERT_EQUAL_INT(-1, agcProcessFrame(&s, NULL, 512));
}

void test_agcProcessFrame_null_state_returns_error(void) {
    int16_t samples[512] = {0};
    TEST_ASSERT_EQUAL_INT(-1, agcProcessFrame(NULL, samples, 512));
}
