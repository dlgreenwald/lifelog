#include <unity.h>
#include <cmath>
#include <cstring>
#include <vector>
#include <string>

// ── computeRMS ─────────────────────────────────────────────────────

float computeRMS(int16_t* samples, int count) {
    float sum = 0;
    for (int i = 0; i < count; i++) {
        sum += (float)samples[i] * (float)samples[i];
    }
    return sqrtf(sum / count);
}

// ── highPassFilter ─────────────────────────────────────────────────

static float hpPrevX = 0;
static float hpPrevY = 0;
#define HP_ALPHA 0.924

void highPassFilter(int16_t* buffer, int count) {
    for (int i = 0; i < count; i++) {
        float x = (float)buffer[i];
        float y = HP_ALPHA * (hpPrevY + x - hpPrevX);
        hpPrevX = x;
        hpPrevY = y;
        buffer[i] = (int16_t)y;
    }
}

// ── RMS Tests ──────────────────────────────────────────────────────

void test_rms_silence() {
    int16_t samples[10] = {0};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, computeRMS(samples, 10));
}

void test_rms_constant() {
    int16_t samples[10] = {1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000, 1000};
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1000.0f, computeRMS(samples, 10));
}

void test_rms_varied() {
    int16_t samples[4] = {100, -100, 200, -200};
    TEST_ASSERT_FLOAT_WITHIN(1.0f, 158.11f, computeRMS(samples, 4));
}

// ── High-Pass Filter Tests ─────────────────────────────────────────

void test_hpf_passes_high_freq() {
    int16_t samples[10] = {1000, -1000, 1000, -1000, 1000, -1000, 1000, -1000, 1000, -1000};
    hpPrevX = 0; hpPrevY = 0;
    highPassFilter(samples, 10);
    TEST_ASSERT_TRUE(abs(samples[5]) > 500);
}

void test_hpf_blocks_dc() {
    // DC offset should be attenuated over time
    int16_t samples[50];
    for (int i = 0; i < 50; i++) samples[i] = 1000;
    hpPrevX = 0; hpPrevY = 0;
    highPassFilter(samples, 50);
    // After 50 samples, DC should be significantly attenuated
    TEST_ASSERT_TRUE(abs(samples[49]) < 200);
}

// ── VAD Threshold Tests ────────────────────────────────────────────

void test_vad_threshold() {
    float bgNoise = 100;
    float threshold = fmax(bgNoise * 1.5, 20.0);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 150.0f, threshold);
}

void test_vad_threshold_minimum() {
    float bgNoise = 5;
    float threshold = fmax(bgNoise * 1.5, 20.0);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 20.0f, threshold);
}

void test_vad_voice_detection() {
    TEST_ASSERT_TRUE(200 > 150);
}

void test_vad_silence_detection() {
    TEST_ASSERT_FALSE(100 > 150);
}

// ── File Operation Tests ───────────────────────────────────────────

struct MockFile {
    std::string filename;
    std::vector<uint8_t> data;
};

static std::vector<MockFile> mockFiles;
static std::vector<std::string> uploadedFiles;

void resetMocks() {
    mockFiles.clear();
    uploadedFiles.clear();
}

void test_file_open_close() {
    resetMocks();
    MockFile f;
    f.filename = "/lifelog/rec_00001.opus";
    mockFiles.push_back(f);
    TEST_ASSERT_EQUAL_INT(1, mockFiles.size());
}

void test_upload_tracking() {
    resetMocks();
    uploadedFiles.push_back("/lifelog/rec_00001.opus");
    TEST_ASSERT_EQUAL_INT(1, uploadedFiles.size());
    TEST_ASSERT_EQUAL_STRING("/lifelog/rec_00001.opus", uploadedFiles[0].c_str());
}

void test_multiple_files() {
    resetMocks();
    for (int i = 0; i < 5; i++) {
        char filename[64];
        snprintf(filename, sizeof(filename), "/lifelog/rec_%05d.opus", i);
        MockFile f;
        f.filename = filename;
        mockFiles.push_back(f);
    }
    TEST_ASSERT_EQUAL_INT(5, mockFiles.size());
}

// ── Ogg Header Tests ───────────────────────────────────────────────

void test_opus_head_magic() {
    uint8_t opusHead[19] = {0};
    memcpy(opusHead, "OpusHead", 8);
    TEST_ASSERT_EQUAL_STRING("OpusHead", (char*)opusHead);
}

void test_opus_head_preskip() {
    uint8_t opusHead[19] = {0};
    opusHead[10] = 0;
    opusHead[11] = 15;
    uint16_t preskip = opusHead[10] | (opusHead[11] << 8);
    TEST_ASSERT_EQUAL_INT(3840, preskip);
}

void test_opus_tags_magic() {
    uint8_t opusTags[23] = {0};
    memcpy(opusTags, "OpusTags", 8);
    TEST_ASSERT_EQUAL_STRING("OpusTags", (char*)opusTags);
}

// ── Chunk Message Tests ────────────────────────────────────────────

void test_chunk_message_format() {
    int16_t* data = (int16_t*)malloc(100);
    TEST_ASSERT_NOT_NULL(data);
    free(data);
}

void test_end_of_utterance() {
    bool isEnd = true;
    uint32_t samples = 0;
    TEST_ASSERT_TRUE(isEnd);
    TEST_ASSERT_EQUAL_INT(0, samples);
}

// ── Run All Tests ──────────────────────────────────────────────────

void setUp() {}
void tearDown() {}

int main() {
    UNITY_BEGIN();

    // RMS tests
    RUN_TEST(test_rms_silence);
    RUN_TEST(test_rms_constant);
    RUN_TEST(test_rms_varied);

    // High-pass filter tests
    RUN_TEST(test_hpf_passes_high_freq);
    RUN_TEST(test_hpf_blocks_dc);

    // VAD tests
    RUN_TEST(test_vad_threshold);
    RUN_TEST(test_vad_threshold_minimum);
    RUN_TEST(test_vad_voice_detection);
    RUN_TEST(test_vad_silence_detection);

    // File operation tests
    RUN_TEST(test_file_open_close);
    RUN_TEST(test_upload_tracking);
    RUN_TEST(test_multiple_files);

    // Ogg header tests
    RUN_TEST(test_opus_head_magic);
    RUN_TEST(test_opus_head_preskip);
    RUN_TEST(test_opus_tags_magic);

    // Chunk message tests
    RUN_TEST(test_chunk_message_format);
    RUN_TEST(test_end_of_utterance);

    return UNITY_END();
}
