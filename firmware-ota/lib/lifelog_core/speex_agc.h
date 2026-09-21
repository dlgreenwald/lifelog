#pragma once
#include <stdint.h>

// SpeexDSP AGC is frame-locked at 160 samples (10ms at 16kHz).
// The AFE fetch delivers 512-sample frames.  We run three 160-sample
// sub-frames and pass the remaining 32 samples through unprocessed.
#define AGC_FRAME_SAMPLES    160
#define AGC_SUB_FRAMES       3   // 3 × 160 = 480
#define AGC_REMAINDER        32  // 512 - 480

// Forward-declare SpeexDSP types (avoids pulling the full
// ESP32-SpeexDSP header into the public header; the implementation
// file includes it).
struct SpeexPreprocessState_;

typedef struct {
    struct SpeexPreprocessState_ *state;
    int sample_rate;
    int frame_size;
} AgcState;

// Must be called once at startup before any speex_preprocess_run() call.
int agcInit(AgcState *s, int sample_rate, int frame_size);

// Must be called at the start of each new utterance (utteranceId increment).
void agcReset(AgcState *s);

// Process a 512-sample AFE frame in-place.  Only the three 160-sample
// sub-frames covered by SPEEX_PREPROCESS_SET_AGC_LEVEL target are AGC'd;
// the final 32-sample remainder passes through unchanged.
// Returns 0 on success, -1 if SpeexDSP is not available.
int agcProcessFrame(AgcState *s, int16_t *samples, int count);
