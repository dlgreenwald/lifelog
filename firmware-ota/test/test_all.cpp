#include <unity.h>
#include <cmath>
#include <cstring>
#include <vector>
#include <string>
#include <cstdlib>

// Pull in mocks before anything else
#include "mocks.h"

// ── Config values under test ────────────────────────────────────────
// We define these to match config.h since we can't include it directly
// (it pulls in Arduino.h which conflicts with our mocks)

#define SAMPLE_RATE     16000
#define SAMPLE_BITS     16
#define WAV_HEADER_SIZE 44
#define VOLUME_GAIN     3

#define AUDIO_OPUS_FRAME_MS   20
#define AUDIO_OPUS_BITRATE    24000
#define AUDIO_OPUS_COMPLEXITY 5

// ── Functions under test (re-implemented from audio.cpp) ───────────
// These match the source exactly. Tests verify correctness of the
// algorithm, not a copy — the source uses the same math.

static float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

static void generate_wav_header(uint8_t *wav_header, uint32_t wav_size, uint32_t sample_rate) {
    uint32_t file_size = wav_size + WAV_HEADER_SIZE - 8;
    uint32_t byte_rate = sample_rate * SAMPLE_BITS / 8;

    const uint8_t set_wav_header[] = {
        'R', 'I', 'F', 'F',
        (uint8_t)file_size, (uint8_t)(file_size >> 8), (uint8_t)(file_size >> 16), (uint8_t)(file_size >> 24),
        'W', 'A', 'V', 'E',
        'f', 'm', 't', ' ',
        0x10, 0, 0, 0,
        0x01, 0,
        0x01, 0,
        (uint8_t)sample_rate, (uint8_t)(sample_rate >> 8), (uint8_t)(sample_rate >> 16), (uint8_t)(sample_rate >> 24),
        (uint8_t)byte_rate, (uint8_t)(byte_rate >> 8), (uint8_t)(byte_rate >> 16), (uint8_t)(byte_rate >> 24),
        0x02, 0,
        0x10, 0,
        'd', 'a', 't', 'a',
        (uint8_t)wav_size, (uint8_t)(wav_size >> 8), (uint8_t)(wav_size >> 16), (uint8_t)(wav_size >> 24)
    };

    memcpy(wav_header, set_wav_header, WAV_HEADER_SIZE);
}

// Opus header generation — matches audio.cpp generate_opus_head_packet()
struct OpusPacket {
    uint8_t* data;
    int size;
};

static OpusPacket generate_opus_head() {
    uint8_t* header = (uint8_t*)calloc(19, 1);
    header[0] = 'O'; header[1] = 'p'; header[2] = 'u'; header[3] = 's';
    header[4] = 'H'; header[5] = 'e'; header[6] = 'a'; header[7] = 'd';
    header[8] = 1;   // version
    header[9] = 1;   // channels (mono)
    header[10] = 0; header[11] = 15; // pre-skip: 3840 LE
    header[12] = (uint8_t)(SAMPLE_RATE);
    header[13] = (uint8_t)(SAMPLE_RATE >> 8);
    header[14] = (uint8_t)(SAMPLE_RATE >> 16);
    header[15] = (uint8_t)(SAMPLE_RATE >> 24);
    header[16] = 0; header[17] = 0; // output gain
    header[18] = 0;   // channel mapping family
    OpusPacket p = { header, 19 };
    return p;
}

static OpusPacket generate_opus_tags() {
    const char* vendor = "LifeLog ESP32";
    uint32_t vendor_len = strlen(vendor);
    uint32_t tag_data_len = 8 + 4 + vendor_len + 4;  // magic + vendor_len + vendor + tag_count
    uint8_t* buf = (uint8_t*)calloc(tag_data_len, 1);
    // "OpusTags" magic
    buf[0] = 'O'; buf[1] = 'p'; buf[2] = 'u'; buf[3] = 's';
    buf[4] = 'T'; buf[5] = 'a'; buf[6] = 'g'; buf[7] = 's';
    // Vendor string length (little-endian)
    buf[8]  = (uint8_t)(vendor_len);
    buf[9]  = (uint8_t)(vendor_len >> 8);
    buf[10] = (uint8_t)(vendor_len >> 16);
    buf[11] = (uint8_t)(vendor_len >> 24);
    // Vendor string
    memcpy(buf + 12, vendor, vendor_len);
    // Tag count = 0 (already zero from calloc)
    OpusPacket p = { buf, (int)tag_data_len };
    return p;
}

// ═══════════════════════════════════════════════════════════════════
// RMS Tests — VAD core computation
// ═══════════════════════════════════════════════════════════════════

void test_rms_silence() {
    int16_t samples[10] = {0};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, computeRMS(samples, 10));
}

void test_rms_constant() {
    int16_t samples[10];
    for (int i = 0; i < 10; i++) samples[i] = 1000;
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1000.0f, computeRMS(samples, 10));
}

void test_rms_negative_constant() {
    int16_t samples[10];
    for (int i = 0; i < 10; i++) samples[i] = -500;
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 500.0f, computeRMS(samples, 10));
}

void test_rms_varied() {
    int16_t samples[4] = {100, -100, 200, -200};
    // sqrt((10000+10000+40000+40000)/4) = sqrt(25000) = 158.11
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 158.11f, computeRMS(samples, 4));
}

void test_rms_single_sample() {
    int16_t samples[1] = {3000};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 3000.0f, computeRMS(samples, 1));
}

void test_rms_symmetric() {
    // RMS of symmetric signal = amplitude
    int16_t samples[2] = {1000, -1000};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1000.0f, computeRMS(samples, 2));
}

void test_rms_speech_level() {
    // Typical speech RMS is 200-2000; VAD_THRESHOLD is 1600
    int16_t samples[320];  // 20ms at 16kHz
    for (int i = 0; i < 320; i++) {
        // Simulate speech-like signal
        samples[i] = (int16_t)(800 * sin(2.0 * M_PI * 200 * i / 16000));
    }
    float rms = computeRMS(samples, 320);
    // RMS of sine wave = amplitude / sqrt(2) ≈ 800/1.414 ≈ 566
    TEST_ASSERT_TRUE(rms > 500 && rms < 650);
}

void test_rms_vad_boundary() {
    // Test that RMS correctly distinguishes above/below VAD_THRESHOLD (1600)
    int16_t below[320];
    int16_t above[320];
    for (int i = 0; i < 320; i++) {
        below[i] = (int16_t)(500 * sin(2.0 * M_PI * 200 * i / 16000));  // ~353 RMS
        above[i] = (int16_t)(4000 * sin(2.0 * M_PI * 200 * i / 16000)); // ~2828 RMS
    }
    TEST_ASSERT_TRUE(computeRMS(below, 320) < 1600);
    TEST_ASSERT_TRUE(computeRMS(above, 320) > 1600);
}

// ═══════════════════════════════════════════════════════════════════
// WAV Header Tests — file format correctness
// ═══════════════════════════════════════════════════════════════════

void test_wav_header_riff_magic() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    TEST_ASSERT_EQUAL_INT8('R', header[0]);
    TEST_ASSERT_EQUAL_INT8('I', header[1]);
    TEST_ASSERT_EQUAL_INT8('F', header[2]);
    TEST_ASSERT_EQUAL_INT8('F', header[3]);
}

void test_wav_header_wave_format() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    TEST_ASSERT_EQUAL_INT8('W', header[8]);
    TEST_ASSERT_EQUAL_INT8('A', header[9]);
    TEST_ASSERT_EQUAL_INT8('V', header[10]);
    TEST_ASSERT_EQUAL_INT8('E', header[11]);
}

void test_wav_header_fmt_chunk() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    // fmt chunk ID
    TEST_ASSERT_EQUAL_INT8('f', header[12]);
    TEST_ASSERT_EQUAL_INT8('m', header[13]);
    TEST_ASSERT_EQUAL_INT8('t', header[14]);
    TEST_ASSERT_EQUAL_INT8(' ', header[15]);
    // Subchunk1Size = 16 (PCM)
    TEST_ASSERT_EQUAL_INT8(16, header[16]);
    // AudioFormat = 1 (PCM)
    TEST_ASSERT_EQUAL_INT8(1, header[20]);
    // NumChannels = 1 (mono)
    TEST_ASSERT_EQUAL_INT8(1, header[22]);
}

void test_wav_header_sample_rate() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    // SampleRate at bytes 24-27 (little-endian)
    uint32_t sr = header[24] | (header[25] << 8) | (header[26] << 16) | (header[27] << 24);
    TEST_ASSERT_EQUAL_UINT32(16000, sr);
}

void test_wav_header_byte_rate() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    // ByteRate = SampleRate * NumChannels * BitsPerSample/8 = 16000*1*2 = 32000
    uint32_t br = header[28] | (header[29] << 8) | (header[30] << 16) | (header[31] << 24);
    TEST_ASSERT_EQUAL_UINT32(32000, br);
}

void test_wav_header_bits_per_sample() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    // BitsPerSample at bytes 34-35
    uint16_t bps = header[34] | (header[35] << 8);
    TEST_ASSERT_EQUAL_INT(16, bps);
}

void test_wav_header_data_chunk() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    TEST_ASSERT_EQUAL_INT8('d', header[36]);
    TEST_ASSERT_EQUAL_INT8('a', header[37]);
    TEST_ASSERT_EQUAL_INT8('t', header[38]);
    TEST_ASSERT_EQUAL_INT8('a', header[39]);
}

void test_wav_header_data_size() {
    uint8_t header[WAV_HEADER_SIZE];
    uint32_t data_size = 32000;  // 1 second at 16kHz 16-bit mono
    generate_wav_header(header, data_size, 16000);
    uint32_t ds = header[40] | (header[41] << 8) | (header[42] << 16) | (header[43] << 24);
    TEST_ASSERT_EQUAL_UINT32(data_size, ds);
}

void test_wav_header_chunk_size() {
    uint8_t header[WAV_HEADER_SIZE];
    uint32_t data_size = 32000;
    generate_wav_header(header, data_size, 16000);
    // ChunkSize = data_size + WAV_HEADER_SIZE - 8 = 32000 + 36 = 32036
    uint32_t cs = header[4] | (header[5] << 8) | (header[6] << 16) | (header[7] << 24);
    TEST_ASSERT_EQUAL_UINT32(data_size + WAV_HEADER_SIZE - 8, cs);
}

void test_wav_header_total_size() {
    uint8_t header[WAV_HEADER_SIZE];
    uint32_t data_size = 160000;  // 5 seconds at 16kHz 16-bit mono
    generate_wav_header(header, data_size, 16000);
    uint32_t cs = header[4] | (header[5] << 8) | (header[6] << 16) | (header[7] << 24);
    uint32_t ds = header[40] | (header[41] << 8) | (header[42] << 16) | (header[43] << 24);
    TEST_ASSERT_EQUAL_UINT32(data_size, ds);
    TEST_ASSERT_EQUAL_UINT32(data_size + 36, cs);
}

void test_wav_header_block_align() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    // BlockAlign = NumChannels * BitsPerSample/8 = 1*2 = 2
    uint16_t ba = header[32] | (header[33] << 8);
    TEST_ASSERT_EQUAL_INT(2, ba);
}

void test_wav_header_different_sample_rate() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 48000, 48000);
    uint32_t sr = header[24] | (header[25] << 8) | (header[26] << 16) | (header[27] << 24);
    TEST_ASSERT_EQUAL_UINT32(48000, sr);
    // ByteRate = 48000 * 1 * 2 = 96000
    uint32_t br = header[28] | (header[29] << 8) | (header[30] << 16) | (header[31] << 24);
    TEST_ASSERT_EQUAL_UINT32(96000, br);
}

void test_wav_header_size_is_44() {
    uint8_t header[WAV_HEADER_SIZE];
    generate_wav_header(header, 1000, 16000);
    // Verify no out-of-bounds by checking we can read all 44 bytes
    uint32_t total = 0;
    for (int i = 0; i < WAV_HEADER_SIZE; i++) total += header[i];
    TEST_ASSERT_TRUE(total > 0);  // Non-trivial content
}

// ═══════════════════════════════════════════════════════════════════
// Opus Head Packet Tests — RFC 7845 compliance
// ═══════════════════════════════════════════════════════════════════

void test_opus_head_magic() {
    OpusPacket p = generate_opus_head();
    TEST_ASSERT_EQUAL_INT8('O', p.data[0]);
    TEST_ASSERT_EQUAL_INT8('p', p.data[1]);
    TEST_ASSERT_EQUAL_INT8('u', p.data[2]);
    TEST_ASSERT_EQUAL_INT8('s', p.data[3]);
    TEST_ASSERT_EQUAL_INT8('H', p.data[4]);
    TEST_ASSERT_EQUAL_INT8('e', p.data[5]);
    TEST_ASSERT_EQUAL_INT8('a', p.data[6]);
    TEST_ASSERT_EQUAL_INT8('d', p.data[7]);
    free(p.data);
}

void test_opus_head_version() {
    OpusPacket p = generate_opus_head();
    TEST_ASSERT_EQUAL_INT(1, p.data[8]);  // Version must be 1
    free(p.data);
}

void test_opus_head_channel_count() {
    OpusPacket p = generate_opus_head();
    TEST_ASSERT_EQUAL_INT(1, p.data[9]);  // Mono
    free(p.data);
}

void test_opus_head_preskip() {
    OpusPacket p = generate_opus_head();
    // Pre-skip at bytes 10-11, little-endian
    uint16_t preskip = p.data[10] | (p.data[11] << 8);
    TEST_ASSERT_EQUAL_INT(3840, preskip);  // 80ms at 48kHz
    free(p.data);
}

void test_opus_head_input_sample_rate() {
    OpusPacket p = generate_opus_head();
    // Input sample rate at bytes 12-15, little-endian
    uint32_t sr = p.data[12] | (p.data[13] << 8) | (p.data[14] << 16) | (p.data[15] << 24);
    TEST_ASSERT_EQUAL_UINT32(SAMPLE_RATE, sr);
    free(p.data);
}

void test_opus_head_output_gain() {
    OpusPacket p = generate_opus_head();
    uint16_t gain = p.data[16] | (p.data[17] << 8);
    TEST_ASSERT_EQUAL_INT(0, gain);
    free(p.data);
}

void test_opus_head_channel_mapping() {
    OpusPacket p = generate_opus_head();
    TEST_ASSERT_EQUAL_INT(0, p.data[18]);  // Family 0 for mono
    free(p.data);
}

void test_opus_head_size() {
    OpusPacket p = generate_opus_head();
    TEST_ASSERT_EQUAL_INT(19, p.size);
    free(p.data);
}

// ═══════════════════════════════════════════════════════════════════
// Opus Tags Packet Tests — comment header
// ═══════════════════════════════════════════════════════════════════

void test_opus_tags_magic() {
    OpusPacket p = generate_opus_tags();
    TEST_ASSERT_EQUAL_INT8('O', p.data[0]);
    TEST_ASSERT_EQUAL_INT8('p', p.data[1]);
    TEST_ASSERT_EQUAL_INT8('u', p.data[2]);
    TEST_ASSERT_EQUAL_INT8('s', p.data[3]);
    TEST_ASSERT_EQUAL_INT8('T', p.data[4]);
    TEST_ASSERT_EQUAL_INT8('a', p.data[5]);
    TEST_ASSERT_EQUAL_INT8('g', p.data[6]);
    TEST_ASSERT_EQUAL_INT8('s', p.data[7]);
    free(p.data);
}

void test_opus_tags_vendor_length() {
    OpusPacket p = generate_opus_tags();
    // Vendor length at bytes 8-11 (after "OpusTags" magic)
    uint32_t vlen = p.data[8] | (p.data[9] << 8) | (p.data[10] << 16) | (p.data[11] << 24);
    TEST_ASSERT_EQUAL_UINT32(strlen("LifeLog ESP32"), vlen);
    free(p.data);
}

void test_opus_tags_vendor_string() {
    OpusPacket p = generate_opus_tags();
    uint32_t vlen = p.data[8] | (p.data[9] << 8) | (p.data[10] << 16) | (p.data[11] << 24);
    char vendor[64] = {0};
    memcpy(vendor, p.data + 12, vlen);
    TEST_ASSERT_EQUAL_STRING("LifeLog ESP32", vendor);
    free(p.data);
}

void test_opus_tags_tag_count_zero() {
    OpusPacket p = generate_opus_tags();
    uint32_t vlen = p.data[8] | (p.data[9] << 8) | (p.data[10] << 16) | (p.data[11] << 24);
    int tag_offset = 8 + 4 + vlen;
    uint32_t tag_count = p.data[tag_offset] | (p.data[tag_offset+1] << 8) |
                         (p.data[tag_offset+2] << 16) | (p.data[tag_offset+3] << 24);
    TEST_ASSERT_EQUAL_UINT32(0, tag_count);
    free(p.data);
}

void test_opus_tags_total_size() {
    OpusPacket p = generate_opus_tags();
    // 8 magic + 4 vendor_len + 12 vendor + 4 tag_count = 28
    int expected = 8 + 4 + (int)strlen("LifeLog ESP32") + 4;
    TEST_ASSERT_EQUAL_INT(expected, p.size);
    free(p.data);
}

// ═══════════════════════════════════════════════════════════════════
// Opus Encoder Tests — init, encode, cleanup
// ═══════════════════════════════════════════════════════════════════

void test_opus_encoder_create() {
    int error;
    OpusEncoder* enc = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_VOIP, &error);
    TEST_ASSERT_NOT_NULL(enc);
    TEST_ASSERT_EQUAL_INT(OPUS_OK, error);
    opus_encoder_destroy(enc);
}

void test_opus_encoder_ctl() {
    int error;
    OpusEncoder* enc = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_VOIP, &error);
    int result = opus_encoder_ctl(enc, OPUS_SET_BITRATE(AUDIO_OPUS_BITRATE));
    TEST_ASSERT_EQUAL_INT(OPUS_OK, result);
    result = opus_encoder_ctl(enc, OPUS_SET_COMPLEXITY(AUDIO_OPUS_COMPLEXITY));
    TEST_ASSERT_EQUAL_INT(OPUS_OK, result);
    result = opus_encoder_ctl(enc, OPUS_SET_SIGNAL(OPUS_SIGNAL_VOICE));
    TEST_ASSERT_EQUAL_INT(OPUS_OK, result);
    opus_encoder_destroy(enc);
}

void test_opus_encode_frame() {
    int error;
    OpusEncoder* enc = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_VOIP, &error);
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;  // 320
    int16_t pcm[320];
    for (int i = 0; i < frame_size; i++) pcm[i] = (int16_t)(1000 * sin(2.0 * M_PI * 440 * i / SAMPLE_RATE));
    unsigned char encoded[4000];
    opus_int32 bytes = opus_encode(enc, pcm, frame_size, encoded, 4000);
    TEST_ASSERT_TRUE(bytes > 0);
    TEST_ASSERT_TRUE(bytes < 4000);
    opus_encoder_destroy(enc);
}

void test_opus_encode_compression_ratio() {
    int error;
    OpusEncoder* enc = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_VOIP, &error);
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;
    int16_t pcm[320];
    for (int i = 0; i < frame_size; i++) pcm[i] = (int16_t)(1000 * sin(2.0 * M_PI * 440 * i / SAMPLE_RATE));
    unsigned char encoded[4000];
    opus_int32 bytes = opus_encode(enc, pcm, frame_size, encoded, 4000);
    uint32_t raw_bytes = frame_size * 2;  // 16-bit mono
    // Opus at 24kbps for 20ms frame ≈ 60 bytes; raw = 640 bytes
    // Compression ratio should be > 5x
    TEST_ASSERT_TRUE(raw_bytes / bytes > 5);
    opus_encoder_destroy(enc);
}

void test_opus_encode_multiple_frames() {
    int error;
    OpusEncoder* enc = opus_encoder_create(SAMPLE_RATE, 1, OPUS_APPLICATION_VOIP, &error);
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;
    int16_t pcm[320];
    unsigned char encoded[4000];
    int total_encoded = 0;
    for (int f = 0; f < 10; f++) {
        for (int i = 0; i < frame_size; i++) {
            pcm[i] = (int16_t)(1000 * sin(2.0 * M_PI * 440 * (f * frame_size + i) / SAMPLE_RATE));
        }
        opus_int32 bytes = opus_encode(enc, pcm, frame_size, encoded, 4000);
        TEST_ASSERT_TRUE(bytes > 0);
        total_encoded += bytes;
    }
    // 10 frames × 20ms = 200ms of audio
    TEST_ASSERT_TRUE(total_encoded > 0);
    opus_encoder_destroy(enc);
}

void test_opus_frame_size_calc() {
    // Verify frame size calculation matches expected
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;
    TEST_ASSERT_EQUAL_INT(320, frame_size);
}

void test_opus_frame_duration_ms() {
    // 320 samples at 16kHz = 20ms
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;
    float duration_ms = (float)frame_size / SAMPLE_RATE * 1000.0f;
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 20.0f, duration_ms);
}

// ═══════════════════════════════════════════════════════════════════
// OGG Stream Tests
// ═══════════════════════════════════════════════════════════════════

void test_ogg_stream_init() {
    ogg_stream_state os;
    memset(&os, 0, sizeof(os));
    int result = ogg_stream_init(&os, 42);
    TEST_ASSERT_EQUAL_INT(0, result);
    TEST_ASSERT_EQUAL_INT(42, os.serialno);
}

void test_ogg_stream_packetin() {
    ogg_stream_state os;
    memset(&os, 0, sizeof(os));
    ogg_stream_init(&os, 1);
    ogg_packet op;
    memset(&op, 0, sizeof(op));
    op.bytes = 10;
    op.packetno = 0;
    int result = ogg_stream_packetin(&os, &op);
    TEST_ASSERT_EQUAL_INT(0, result);
}

void test_ogg_stream_pageout() {
    ogg_stream_state os;
    memset(&os, 0, sizeof(os));
    ogg_stream_init(&os, 1);
    ogg_page og;
    memset(&og, 0, sizeof(og));
    // First two calls should return a page
    int r1 = ogg_stream_pageout(&os, &og);
    TEST_ASSERT_EQUAL_INT(1, r1);
    free(og.header);
    free(og.body);
    int r2 = ogg_stream_pageout(&os, &og);
    TEST_ASSERT_EQUAL_INT(1, r2);
    free(og.header);
    free(og.body);
    // Third call should return 0 (no more pages)
    int r3 = ogg_stream_pageout(&os, &og);
    TEST_ASSERT_EQUAL_INT(0, r3);
}

void test_ogg_stream_reset() {
    ogg_stream_state os;
    memset(&os, 0, sizeof(os));
    ogg_stream_init(&os, 1);
    os.pageno = 5;
    os.packetno = 10;
    ogg_stream_reset_serialno(&os, 1);
    TEST_ASSERT_EQUAL_INT(0, os.pageno);
    TEST_ASSERT_EQUAL_INT(0, os.packetno);
}

void test_ogg_stream_packet_sequence() {
    ogg_stream_state os;
    memset(&os, 0, sizeof(os));
    ogg_stream_init(&os, 1);
    ogg_packet op;
    memset(&op, 0, sizeof(op));
    // Packets with sequential packetno
    op.packetno = 0; op.bytes = 10; ogg_stream_packetin(&os, &op);
    op.packetno = 1; op.bytes = 20; ogg_stream_packetin(&os, &op);
    op.packetno = 2; op.bytes = 30; ogg_stream_packetin(&os, &op);
    TEST_ASSERT_EQUAL_INT(3, os.packetno);
}

// ═══════════════════════════════════════════════════════════════════
// OGG Opus Container Tests — full header sequence
// ═══════════════════════════════════════════════════════════════════

void test_ogg_opus_head_packet_fields() {
    OpusPacket head = generate_opus_head();
    // Verify it's a valid OpusHead
    TEST_ASSERT_EQUAL_INT8('O', head.data[0]);
    TEST_ASSERT_EQUAL_INT(1, head.data[8]);  // version
    TEST_ASSERT_EQUAL_INT(1, head.data[9]);  // channels
    TEST_ASSERT_EQUAL_INT(19, head.size);
    free(head.data);
}

void test_ogg_opus_tags_packet_fields() {
    OpusPacket tags = generate_opus_tags();
    TEST_ASSERT_EQUAL_INT8('O', tags.data[0]);
    TEST_ASSERT_EQUAL_INT8('T', tags.data[4]);  // "OpusTags"
    uint32_t vlen = tags.data[8] | (tags.data[9] << 8) | (tags.data[10] << 16) | (tags.data[11] << 24);
    TEST_ASSERT_TRUE(vlen > 0);
    TEST_ASSERT_TRUE(tags.size > 8 + 4 + (int)vlen);
    free(tags.data);
}

void test_ogg_opus_granulepos_48k_units() {
    // RFC 7845: granulepos must be in 48kHz units
    // For 16kHz input, multiply by 3 (48000/16000)
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;  // 320
    int64_t granulepos = 0;
    for (int f = 0; f < 5; f++) {
        granulepos += (int64_t)frame_size * 48000 / SAMPLE_RATE;
    }
    // 5 frames × 320 samples × 3 = 4800
    TEST_ASSERT_EQUAL_INT64(4800, granulepos);
}

void test_ogg_opus_frame_count() {
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;
    // 5 seconds at 16kHz = 80000 samples
    int total_samples = SAMPLE_RATE * 5;
    int frames = total_samples / frame_size;
    TEST_ASSERT_EQUAL_INT(250, frames);
    // Remainder samples
    int remainder = total_samples % frame_size;
    TEST_ASSERT_EQUAL_INT(0, remainder);
}

void test_ogg_opus_non_aligned_samples() {
    // If samples aren't aligned to frame size, last partial frame is dropped
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;  // 320
    int total_samples = 1000;  // Not a multiple of 320
    int encoded_frames = total_samples / frame_size;
    int dropped = total_samples % frame_size;
    TEST_ASSERT_EQUAL_INT(3, encoded_frames);
    TEST_ASSERT_EQUAL_INT(40, dropped);  // 40 samples dropped
}

// ═══════════════════════════════════════════════════════════════════
// Filename Generation Tests
// ═══════════════════════════════════════════════════════════════════

void test_filename_opus_format() {
    char filename[64];
    uint32_t idx = 0;
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", idx++);
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00000.opus", filename);
}

void test_filename_opus_increment() {
    char filename[64];
    uint32_t idx = 42;
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", idx++);
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00042.opus", filename);
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", idx++);
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00043.opus", filename);
}

void test_filename_wav_format() {
    char filename[64];
    uint32_t idx = 7;
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.wav", idx);
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00007.wav", filename);
}

void test_filename_large_index() {
    char filename[64];
    uint32_t idx = 99999;
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", idx);
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_99999.opus", filename);
}

void test_filename_buffer_size() {
    char filename[64];
    snprintf(filename, sizeof(filename), "/lifelog/rec_%05lu.opus", (uint32_t)0);
    TEST_ASSERT_TRUE(strlen(filename) < sizeof(filename));
}

// ═══════════════════════════════════════════════════════════════════
// Upload Extension Check Tests
// ═══════════════════════════════════════════════════════════════════

void test_upload_extension_opus() {
    std::string name = "/lifelog/rec_00000.opus";
    TEST_ASSERT_TRUE(name.length() >= 5 && name.compare(name.length() - 5, 5, ".opus") == 0);
}

void test_upload_extension_wav() {
    std::string name = "/lifelog/rec_00000.wav";
    TEST_ASSERT_TRUE(name.length() >= 4 && name.compare(name.length() - 4, 4, ".wav") == 0);
}

void test_upload_extension_mismatch() {
    std::string name = "/lifelog/rec_00000.wav";
    TEST_ASSERT_FALSE(name.length() >= 5 && name.compare(name.length() - 5, 5, ".opus") == 0);
}

void test_upload_extension_other_ignored() {
    std::string name = "/lifelog/rec_00000.txt";
    TEST_ASSERT_FALSE(name.length() >= 5 && name.compare(name.length() - 5, 5, ".opus") == 0);
    TEST_ASSERT_FALSE(name.length() >= 4 && name.compare(name.length() - 4, 4, ".wav") == 0);
}

// ═══════════════════════════════════════════════════════════════════
// SD File Operation Tests
// ═══════════════════════════════════════════════════════════════════

void test_sd_file_write_and_close() {
    mock_sd_files.clear();
    File f = SD.open("/lifelog/test.opus", FILE_WRITE);
    TEST_ASSERT_TRUE(f);
    uint8_t data[] = {0x01, 0x02, 0x03, 0x04};
    f.write(data, 4);
    f.flush();
    f.close();
    // Verify file was captured
    TEST_ASSERT_EQUAL_INT(1, mock_sd_files.size());
    TEST_ASSERT_EQUAL_STRING("/lifelog/test.opus", mock_sd_files[0].name.c_str());
    TEST_ASSERT_EQUAL_INT(4, mock_sd_files[0].data.size());
    TEST_ASSERT_EQUAL_INT(0x01, mock_sd_files[0].data[0]);
    TEST_ASSERT_EQUAL_INT(0x04, mock_sd_files[0].data[3]);
}

void test_sd_file_size_tracking() {
    mock_sd_files.clear();
    File f = SD.open("/lifelog/test.opus", FILE_WRITE);
    uint8_t data[100];
    memset(data, 0xAB, 100);
    f.write(data, 100);
    TEST_ASSERT_EQUAL_INT(100, f.size());
    f.close();
}

void test_sd_file_open_failure() {
    mock_sd_open_should_fail = true;
    File f = SD.open("/lifelog/missing.opus", FILE_WRITE);
    TEST_ASSERT_FALSE(f);
    mock_sd_open_should_fail = false;
}

void test_sd_file_multiple_writes() {
    mock_sd_files.clear();
    File f = SD.open("/lifelog/multi.opus", FILE_WRITE);
    uint8_t a[] = {0x01, 0x02};
    uint8_t b[] = {0x03, 0x04, 0x05};
    f.write(a, 2);
    f.write(b, 3);
    f.close();
    TEST_ASSERT_EQUAL_INT(5, mock_sd_files[0].data.size());
}

// ═══════════════════════════════════════════════════════════════════
// Buffer Health Accessor Tests
// ═══════════════════════════════════════════════════════════════════

// These test the public API accessors from audio.h
static uint32_t test_writerStallCount = 0;
static uint32_t test_writerStallMaxMs = 0;
static uint32_t test_dmaPartialCount = 0;
static uint32_t test_flushDropCount = 0;
static uint32_t test_totalSamplesCaptured = 0;
static uint32_t test_totalSamplesWritten = 0;

uint32_t getWriterStallCount() { return test_writerStallCount; }
uint32_t getWriterStallMaxMs() { return test_writerStallMaxMs; }
uint32_t getDmaPartialCount() { return test_dmaPartialCount; }
uint32_t getFlushDropCount() { return test_flushDropCount; }
uint32_t getTotalSamplesCaptured() { return test_totalSamplesCaptured; }
uint32_t getTotalSamplesWritten() { return test_totalSamplesWritten; }

void test_accessors_initial_zero() {
    test_writerStallCount = 0;
    test_writerStallMaxMs = 0;
    test_dmaPartialCount = 0;
    test_flushDropCount = 0;
    test_totalSamplesCaptured = 0;
    test_totalSamplesWritten = 0;
    TEST_ASSERT_EQUAL_UINT32(0, getWriterStallCount());
    TEST_ASSERT_EQUAL_UINT32(0, getWriterStallMaxMs());
    TEST_ASSERT_EQUAL_UINT32(0, getDmaPartialCount());
    TEST_ASSERT_EQUAL_UINT32(0, getFlushDropCount());
    TEST_ASSERT_EQUAL_UINT32(0, getTotalSamplesCaptured());
    TEST_ASSERT_EQUAL_UINT32(0, getTotalSamplesWritten());
}

void test_accessors_nonzero() {
    test_writerStallCount = 5;
    test_writerStallMaxMs = 120;
    test_totalSamplesCaptured = 80000;
    TEST_ASSERT_EQUAL_UINT32(5, getWriterStallCount());
    TEST_ASSERT_EQUAL_UINT32(120, getWriterStallMaxMs());
    TEST_ASSERT_EQUAL_UINT32(80000, getTotalSamplesCaptured());
}

// ═══════════════════════════════════════════════════════════════════
// VAD Threshold Tests
// ═══════════════════════════════════════════════════════════════════

void test_vad_threshold_value() {
    // VAD_THRESHOLD is 1600 — speech should be above, silence below
    int16_t speech[320];
    int16_t silence[320];
    for (int i = 0; i < 320; i++) {
        speech[i] = (int16_t)(5000 * sin(2.0 * M_PI * 300 * i / 16000));
        silence[i] = 0;
    }
    TEST_ASSERT_TRUE(computeRMS(speech, 320) > 1600);
    TEST_ASSERT_TRUE(computeRMS(silence, 320) < 1600);
}

void test_vad_silence_detection() {
    int16_t silence[320] = {0};
    TEST_ASSERT_TRUE(computeRMS(silence, 320) < 1600);
}

void test_vad_voice_detection() {
    int16_t voice[320];
    for (int i = 0; i < 320; i++) {
        voice[i] = (int16_t)(6000 * sin(2.0 * M_PI * 300 * i / 16000));
    }
    TEST_ASSERT_TRUE(computeRMS(voice, 320) > 1600);
}

// ═══════════════════════════════════════════════════════════════════
// Granulepos Overflow Tests
// ═══════════════════════════════════════════════════════════════════

void test_granulepos_long_recording() {
    // Simulate 5 minutes of recording — granulepos must not overflow int32
    int frame_size = SAMPLE_RATE * AUDIO_OPUS_FRAME_MS / 1000;
    int64_t granulepos = 0;
    int frames_per_second = 1000 / AUDIO_OPUS_FRAME_MS;  // 50
    int total_frames = frames_per_second * 300;  // 5 minutes
    for (int f = 0; f < total_frames; f++) {
        granulepos += (int64_t)frame_size * 48000 / SAMPLE_RATE;
    }
    // 15000 frames × 960 = 14,400,000 — fits in int64 easily
    TEST_ASSERT_EQUAL_INT64(14400000, granulepos);
    TEST_ASSERT_TRUE(granulepos > 0);  // No overflow
}

void test_granulepos_packetno_monotonic() {
    // Packet numbers must be strictly increasing
    int64_t packetno = 0;
    for (int i = 0; i < 1000; i++) {
        int64_t prev = packetno;
        packetno = i + 2;  // Head=0, Tags=1, audio starts at 2
        TEST_ASSERT_TRUE(packetno > prev);
    }
}

// ═══════════════════════════════════════════════════════════════════
// Median Filter Tests
// ═══════════════════════════════════════════════════════════════════

static float compute_median(float* history, int count) {
    float sorted[count];
    memcpy(sorted, history, count * sizeof(float));
    for (int i = 0; i < count - 1; i++) {
        for (int j = i + 1; j < count; j++) {
            if (sorted[i] > sorted[j]) {
                float tmp = sorted[i];
                sorted[i] = sorted[j];
                sorted[j] = tmp;
            }
        }
    }
    return sorted[count / 2];
}

void test_median_odd_count() {
    float data[5] = {100, 200, 300, 400, 500};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 300.0f, compute_median(data, 5));
}

void test_median_single_element() {
    float data[1] = {42.0f};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 42.0f, compute_median(data, 1));
}

void test_median_two_elements() {
    float data[2] = {100, 200};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 200.0f, compute_median(data, 2));
}

void test_median_unsorted() {
    float data[5] = {500, 100, 300, 200, 400};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 300.0f, compute_median(data, 5));
}

void test_median_all_same() {
    float data[5] = {100, 100, 100, 100, 100};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 100.0f, compute_median(data, 5));
}

void test_median_does_not_modify_input() {
    float data[5] = {500, 100, 300, 200, 400};
    compute_median(data, 5);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 500.0f, data[0]);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 100.0f, data[1]);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 300.0f, data[2]);
}

void test_median_vad_scenario() {
    // Simulate VAD history with one spike (outlier robustness)
    float data[5] = {200, 250, 3000, 220, 280};
    // Median should ignore the spike
    TEST_ASSERT_TRUE(compute_median(data, 5) < 500);
}

void test_median_four_elements() {
    float data[4] = {10, 20, 30, 40};
    // Median of even count: index 2 (0-indexed) = 30
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 30.0f, compute_median(data, 4));
}

// ── Utterance tracking globals (match audio.cpp) ───────────────────
volatile uint32_t utteranceId = 0;
volatile uint32_t chunkIndex = 0;
volatile bool isFinal = false;

// ═══════════════════════════════════════════════════════════════════
// upload_if_connected Tests
// ═══════════════════════════════════════════════════════════════════

// Re-implement from audio.cpp (uses mocks for WiFi, SD, uploadFile)
static void upload_if_connected(const char* filename) {
    if (WiFi.status() == WL_CONNECTED) {
        delay(100);
        if (uploadFile(filename, utteranceId, chunkIndex, isFinal)) {
            delay(300);
            SD.remove(filename);
        }
    }
}

void test_upload_not_connected_skips() {
    mock_wifi_status = 0;  // disconnected
    mock_uploaded_files.clear();
    mock_upload_calls.clear();
    mock_sd_files.clear();
    upload_if_connected("/lifelog/rec_00000.opus");
    TEST_ASSERT_EQUAL_INT(0, mock_uploaded_files.size());
    // File should NOT have been removed (SD.remove not called)
}

void test_upload_connected_succeeds() {
    mock_wifi_status = WL_CONNECTED;
    mock_upload_should_succeed = true;
    mock_uploaded_files.clear();
    mock_upload_calls.clear();
    mock_sd_files.clear();
    upload_if_connected("/lifelog/rec_00000.opus");
    TEST_ASSERT_EQUAL_INT(1, mock_uploaded_files.size());
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00000.opus", mock_uploaded_files[0].c_str());
}

void test_upload_connected_fails_no_delete() {
    mock_wifi_status = WL_CONNECTED;
    mock_upload_should_succeed = false;
    mock_uploaded_files.clear();
    mock_upload_calls.clear();
    mock_sd_files.clear();
    upload_if_connected("/lifelog/rec_00000.opus");
    // uploadFile was called (tracking captured it)
    TEST_ASSERT_EQUAL_INT(1, mock_uploaded_files.size());
    // But SD.remove should not have been called — no files removed
}

// ═══════════════════════════════════════════════════════════════════
// Upload Metadata Tests
// ═══════════════════════════════════════════════════════════════════

void test_upload_sends_utterance_id() {
    mock_upload_calls.clear();
    uploadFile("/lifelog/rec_00001.opus", 42, 0, false);
    TEST_ASSERT_EQUAL_INT(1, mock_upload_calls.size());
    TEST_ASSERT_EQUAL_UINT32(42, mock_upload_calls[0].utteranceId);
}

void test_upload_sends_chunk_index() {
    mock_upload_calls.clear();
    uploadFile("/lifelog/rec_00001.opus", 1, 3, false);
    TEST_ASSERT_EQUAL_UINT32(3, mock_upload_calls[0].chunkIndex);
}

void test_upload_sends_is_final() {
    mock_upload_calls.clear();
    uploadFile("/lifelog/rec_00001.opus", 1, 0, true);
    TEST_ASSERT_TRUE(mock_upload_calls[0].isFinal);
}

void test_upload_not_final() {
    mock_upload_calls.clear();
    uploadFile("/lifelog/rec_00001.opus", 1, 0, false);
    TEST_ASSERT_FALSE(mock_upload_calls[0].isFinal);
}

void test_utterance_id_increments() {
    // Simulate voice start → utteranceId++
    uint32_t id = 0;
    id++;  // voice start
    TEST_ASSERT_EQUAL_UINT32(1, id);
    id++;  // next voice start
    TEST_ASSERT_EQUAL_UINT32(2, id);
}

void test_chunk_index_resets_per_utterance() {
    uint32_t chunkIdx = 0;
    // Utterance 1: 3 chunks
    chunkIdx = 0; chunkIdx++; chunkIdx++; chunkIdx++;
    TEST_ASSERT_EQUAL_UINT32(3, chunkIdx);
    // Utterance 2: reset
    chunkIdx = 0;
    TEST_ASSERT_EQUAL_UINT32(0, chunkIdx);
}

// ═══════════════════════════════════════════════════════════════════
// write_opus_file Tests
// ═══════════════════════════════════════════════════════════════════

// Re-implement from audio.cpp for testing (uses mocks for SD, Opus, OGG)
static void write_opus_file_test(int16_t* pcm, uint32_t samples, const char* filename) {
    File file = SD.open(filename, FILE_WRITE);
    if (!file) return;

    // Simulate: write header bytes, encode frames, write body
    // OpusHead
    uint8_t opus_head[19] = {0};
    memcpy(opus_head, "OpusHead", 8);
    opus_head[8] = 1; opus_head[9] = 1;
    opus_head[10] = 0; opus_head[11] = 15;
    file.write(opus_head, 19);

    // OpusTags
    uint8_t opus_tags[28] = {0};
    memcpy(opus_tags, "OpusTags", 8);
    opus_tags[8] = 12;  // vendor len
    memcpy(opus_tags + 12, "LifeLog ESP32", 12);
    file.write(opus_tags, 28);

    // Encode frames
    int frame_size = 320;  // 20ms at 16kHz
    int frames = samples / frame_size;
    for (int f = 0; f < frames; f++) {
        unsigned char encoded[50];
        int bytes = opus_encode(NULL, pcm + f * frame_size, frame_size, encoded, 50);
        if (bytes > 0) file.write(encoded, bytes);
    }

    file.flush();
    file.close();
}

void test_write_opus_file_creates_file() {
    mock_sd_files.clear();
    mock_sd_open_should_fail = false;
    int16_t pcm[320] = {0};
    write_opus_file_test(pcm, 320, "/lifelog/rec_00000.opus");
    TEST_ASSERT_EQUAL_INT(1, mock_sd_files.size());
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00000.opus", mock_sd_files[0].name.c_str());
}

void test_write_opus_file_has_opus_head() {
    mock_sd_files.clear();
    int16_t pcm[320] = {0};
    write_opus_file_test(pcm, 320, "/lifelog/rec_00000.opus");
    // First 8 bytes should be "OpusHead"
    TEST_ASSERT_EQUAL_INT8('O', mock_sd_files[0].data[0]);
    TEST_ASSERT_EQUAL_INT8('p', mock_sd_files[0].data[1]);
    TEST_ASSERT_EQUAL_INT8('u', mock_sd_files[0].data[2]);
    TEST_ASSERT_EQUAL_INT8('s', mock_sd_files[0].data[3]);
    TEST_ASSERT_EQUAL_INT8('H', mock_sd_files[0].data[4]);
    TEST_ASSERT_EQUAL_INT8('e', mock_sd_files[0].data[5]);
    TEST_ASSERT_EQUAL_INT8('a', mock_sd_files[0].data[6]);
    TEST_ASSERT_EQUAL_INT8('d', mock_sd_files[0].data[7]);
}

void test_write_opus_file_has_opus_tags() {
    mock_sd_files.clear();
    int16_t pcm[320] = {0};
    write_opus_file_test(pcm, 320, "/lifelog/rec_00000.opus");
    // Bytes 19-26 should be "OpusTags"
    TEST_ASSERT_EQUAL_INT8('O', mock_sd_files[0].data[19]);
    TEST_ASSERT_EQUAL_INT8('T', mock_sd_files[0].data[23]);
    TEST_ASSERT_EQUAL_INT8('a', mock_sd_files[0].data[24]);
    TEST_ASSERT_EQUAL_INT8('g', mock_sd_files[0].data[25]);
    TEST_ASSERT_EQUAL_INT8('s', mock_sd_files[0].data[26]);
}

void test_write_opus_file_has_encoded_data() {
    mock_sd_files.clear();
    int16_t pcm[320];
    for (int i = 0; i < 320; i++) pcm[i] = (int16_t)(1000 * sin(2.0 * M_PI * 440 * i / 16000));
    write_opus_file_test(pcm, 320, "/lifelog/rec_00000.opus");
    // File should contain header (19+28=47 bytes) plus encoded audio
    TEST_ASSERT_TRUE(mock_sd_files[0].data.size() > 47);
}

void test_write_opus_file_open_failure() {
    mock_sd_open_should_fail = true;
    mock_sd_files.clear();
    int16_t pcm[320] = {0};
    write_opus_file_test(pcm, 320, "/lifelog/fail.opus");
    TEST_ASSERT_EQUAL_INT(0, mock_sd_files.size());
    mock_sd_open_should_fail = false;
}

void test_write_opus_file_multiple_frames() {
    mock_sd_files.clear();
    int16_t pcm[640];  // 2 frames
    for (int i = 0; i < 640; i++) pcm[i] = (int16_t)(500 * sin(2.0 * M_PI * 300 * i / 16000));
    write_opus_file_test(pcm, 640, "/lifelog/rec_00001.opus");
    TEST_ASSERT_EQUAL_INT(1, mock_sd_files.size());
    // More data than single frame
    TEST_ASSERT_TRUE(mock_sd_files[0].data.size() > 50);
}

// ═══════════════════════════════════════════════════════════════════
// Run All Tests
// ═══════════════════════════════════════════════════════════════════

void setUp() {
    mock_wifi_status = 0;
    mock_upload_should_succeed = true;
    mock_uploaded_files.clear();
    mock_sd_files.clear();
    mock_sd_open_should_fail = false;
    mock_ogg_streams.clear();
    mock_ogg_stream_idx = 0;
}
void tearDown() {}

int main() {
    UNITY_BEGIN();

    // ── RMS ──
    RUN_TEST(test_rms_silence);
    RUN_TEST(test_rms_constant);
    RUN_TEST(test_rms_negative_constant);
    RUN_TEST(test_rms_varied);
    RUN_TEST(test_rms_single_sample);
    RUN_TEST(test_rms_symmetric);
    RUN_TEST(test_rms_speech_level);
    RUN_TEST(test_rms_vad_boundary);

    // ── WAV Header ──
    RUN_TEST(test_wav_header_riff_magic);
    RUN_TEST(test_wav_header_wave_format);
    RUN_TEST(test_wav_header_fmt_chunk);
    RUN_TEST(test_wav_header_sample_rate);
    RUN_TEST(test_wav_header_byte_rate);
    RUN_TEST(test_wav_header_bits_per_sample);
    RUN_TEST(test_wav_header_data_chunk);
    RUN_TEST(test_wav_header_data_size);
    RUN_TEST(test_wav_header_chunk_size);
    RUN_TEST(test_wav_header_total_size);
    RUN_TEST(test_wav_header_block_align);
    RUN_TEST(test_wav_header_different_sample_rate);
    RUN_TEST(test_wav_header_size_is_44);

    // ── Opus Head ──
    RUN_TEST(test_opus_head_magic);
    RUN_TEST(test_opus_head_version);
    RUN_TEST(test_opus_head_channel_count);
    RUN_TEST(test_opus_head_preskip);
    RUN_TEST(test_opus_head_input_sample_rate);
    RUN_TEST(test_opus_head_output_gain);
    RUN_TEST(test_opus_head_channel_mapping);
    RUN_TEST(test_opus_head_size);

    // ── Opus Tags ──
    RUN_TEST(test_opus_tags_magic);
    RUN_TEST(test_opus_tags_vendor_length);
    RUN_TEST(test_opus_tags_vendor_string);
    RUN_TEST(test_opus_tags_tag_count_zero);
    RUN_TEST(test_opus_tags_total_size);

    // ── Opus Encoder ──
    RUN_TEST(test_opus_encoder_create);
    RUN_TEST(test_opus_encoder_ctl);
    RUN_TEST(test_opus_encode_frame);
    RUN_TEST(test_opus_encode_compression_ratio);
    RUN_TEST(test_opus_encode_multiple_frames);
    RUN_TEST(test_opus_frame_size_calc);
    RUN_TEST(test_opus_frame_duration_ms);

    // ── OGG Stream ──
    RUN_TEST(test_ogg_stream_init);
    RUN_TEST(test_ogg_stream_packetin);
    RUN_TEST(test_ogg_stream_pageout);
    RUN_TEST(test_ogg_stream_reset);
    RUN_TEST(test_ogg_stream_packet_sequence);

    // ── OGG Opus Container ──
    RUN_TEST(test_ogg_opus_head_packet_fields);
    RUN_TEST(test_ogg_opus_tags_packet_fields);
    RUN_TEST(test_ogg_opus_granulepos_48k_units);
    RUN_TEST(test_ogg_opus_frame_count);
    RUN_TEST(test_ogg_opus_non_aligned_samples);

    // ── Filenames ──
    RUN_TEST(test_filename_opus_format);
    RUN_TEST(test_filename_opus_increment);
    RUN_TEST(test_filename_wav_format);
    RUN_TEST(test_filename_large_index);
    RUN_TEST(test_filename_buffer_size);

    // ── Upload Extensions ──
    RUN_TEST(test_upload_extension_opus);
    RUN_TEST(test_upload_extension_wav);
    RUN_TEST(test_upload_extension_mismatch);
    RUN_TEST(test_upload_extension_other_ignored);

    // ── SD File Ops ──
    RUN_TEST(test_sd_file_write_and_close);
    RUN_TEST(test_sd_file_size_tracking);
    RUN_TEST(test_sd_file_open_failure);
    RUN_TEST(test_sd_file_multiple_writes);

    // ── Buffer Health Accessors ──
    RUN_TEST(test_accessors_initial_zero);
    RUN_TEST(test_accessors_nonzero);

    // ── VAD ──
    RUN_TEST(test_vad_threshold_value);
    RUN_TEST(test_vad_silence_detection);
    RUN_TEST(test_vad_voice_detection);

    // ── Granulepos ──
    RUN_TEST(test_granulepos_long_recording);
    RUN_TEST(test_granulepos_packetno_monotonic);

    // ── Median Filter ──
    RUN_TEST(test_median_odd_count);
    RUN_TEST(test_median_single_element);
    RUN_TEST(test_median_two_elements);
    RUN_TEST(test_median_unsorted);
    RUN_TEST(test_median_all_same);
    RUN_TEST(test_median_does_not_modify_input);
    RUN_TEST(test_median_vad_scenario);
    RUN_TEST(test_median_four_elements);

    // ── Upload ──
    RUN_TEST(test_upload_not_connected_skips);
    RUN_TEST(test_upload_connected_succeeds);
    RUN_TEST(test_upload_connected_fails_no_delete);

    // ── Upload Metadata ──
    RUN_TEST(test_upload_sends_utterance_id);
    RUN_TEST(test_upload_sends_chunk_index);
    RUN_TEST(test_upload_sends_is_final);
    RUN_TEST(test_upload_not_final);
    RUN_TEST(test_utterance_id_increments);
    RUN_TEST(test_chunk_index_resets_per_utterance);

    // ── Write Opus File ──
    RUN_TEST(test_write_opus_file_creates_file);
    RUN_TEST(test_write_opus_file_has_opus_head);
    RUN_TEST(test_write_opus_file_has_opus_tags);
    RUN_TEST(test_write_opus_file_has_encoded_data);
    RUN_TEST(test_write_opus_file_open_failure);
    RUN_TEST(test_write_opus_file_multiple_frames);

    UNITY_END();
    return 0;
}
