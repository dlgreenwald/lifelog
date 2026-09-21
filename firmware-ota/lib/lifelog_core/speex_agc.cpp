#include "speex_agc.h"
#include <cstring>

// ESP32-SpeexDSP is only available on the ESP32 target.
// For the native test environment we rely on mocks in test/mocks.h.
#ifdef ARDUINO_ARCH_ESP32
#include <ESP32-SpeexDSP.h>
#else
// External linkage — the test environment provides these via mocks.h
extern "C" {
    struct SpeexPreprocessState_;
    typedef struct SpeexPreprocessState_ SpeexPreprocessState;

    SpeexPreprocessState* speex_preprocess_state_init(int frame_size, int sampling_rate);
    void speex_preprocess_state_destroy(SpeexPreprocessState* st);
    int speex_preprocess_run(SpeexPreprocessState* st, int16_t* x);
    int speex_preprocess_ctl(SpeexPreprocessState* st, int request, void* ptr);

    #define SPEEX_PREPROCESS_SET_AGC 2
    #define SPEEX_PREPROCESS_SET_AGC_LEVEL 6
    #define SPEEX_PREPROCESS_SET_NOISE_SUPPRESS 18
    #define SPEEX_PREPROCESS_SET_VAD 4
    #define SPEEX_PREPROCESS_SET_DEREVERB 8
    #define SPEEX_PREPROCESS_SET_AGC_MAX_GAIN 30
}
#endif

// IRAM_ATTR: called from i2s_fe feed task on limited stack; AGC sub-frames
// are small (160 samples) so inlining is safe and eliminates cross-1GB-boundary
// calls that the ESP32 Xtensa linker rejects as "dangerous relocation".
#ifdef ARDUINO_ARCH_ESP32
#define AgcFunc IRAM_ATTR int
#else
#define AgcFunc int
#endif

AgcFunc agcInit(AgcState *s, int sample_rate, int frame_size) {
    if (!s) return -1;

    s->sample_rate = sample_rate;
    s->frame_size = frame_size;

    s->state = speex_preprocess_state_init(frame_size, sample_rate);
    if (!s->state) return -1;

    // Enable AGC
    int agc_enable = 1;
    if (speex_preprocess_ctl(s->state, SPEEX_PREPROCESS_SET_AGC, &agc_enable) != 0) {
        speex_preprocess_state_destroy(s->state);
        s->state = NULL;
        return -1;
    }

    // Target 0.6 (linear, 0.6 ≈ -4.4 dBFS — comfortable speech level)
    float agc_level = 0.6f;
    if (speex_preprocess_ctl(s->state, SPEEX_PREPROCESS_SET_AGC_LEVEL, &agc_level) != 0) {
        speex_preprocess_state_destroy(s->state);
        s->state = NULL;
        return -1;
    }

    // Disable NS — AFE already ran nsnet2; SpeexDSP NS is redundant
    int nsSuppress = -100;
    speex_preprocess_ctl(s->state, SPEEX_PREPROCESS_SET_NOISE_SUPPRESS, &nsSuppress);

    // Disable SpeexDSP VAD — AFE already provides VAD decisions
    int vad_enable = 0;
    speex_preprocess_ctl(s->state, SPEEX_PREPROCESS_SET_VAD, &vad_enable);

    // Disable dereverb
    int dereverb = 0;
    speex_preprocess_ctl(s->state, SPEEX_PREPROCESS_SET_DEREVERB, &dereverb);

    // Cap max gain at 20 dB to avoid amplifying noise in quiet passages
    int max_gain = 20;
    speex_preprocess_ctl(s->state, SPEEX_PREPROCESS_SET_AGC_MAX_GAIN, &max_gain);

    return 0;
}

AgcFunc agcReset(AgcState *s) {
    if (!s) return;

    if (s->state) {
        speex_preprocess_state_destroy(s->state);
        s->state = NULL;
    }

    // Re-initialise to clear gain history between utterances
    agcInit(s, s->sample_rate, s->frame_size);
}

AgcFunc agcProcessFrame(AgcState *s, int16_t *samples, int count) {
    if (!s || !s->state || !samples || count <= 0) return -1;

    // VAD cache path — non-512 sample frames pass through unprocessed
    // (first chunk of utterance, partial frames, etc.)
    if (count != 512) {
        return 0;
    }

    // Process three 160-sample sub-frames; the final 32 samples pass through
    int16_t sub_frame[AGC_FRAME_SAMPLES];

    for (int i = 0; i < AGC_SUB_FRAMES; i++) {
        memcpy(sub_frame, samples + i * AGC_FRAME_SAMPLES, AGC_FRAME_SAMPLES * sizeof(int16_t));
        speex_preprocess_run(s->state, sub_frame);
        memcpy(samples + i * AGC_FRAME_SAMPLES, sub_frame, AGC_FRAME_SAMPLES * sizeof(int16_t));
    }

    // Remaining 32 samples are already in place (passed through unprocessed)
    return 0;
}
