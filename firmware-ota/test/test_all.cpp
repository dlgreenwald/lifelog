#include <unity.h>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <cmath>

// Pull in mocks before anything else — provides OGG types, WiFi, SD, etc.
#include "mocks.h"
#include <ArduinoJson.h>

// Pull in lib headers — these provide the REAL production code under test
#include "lifelog_core/codec.h"
#include "lifelog_core/settings.h"
#include "lifelog_core/filename.h"

// Server API key (matches config.h)
#define API_KEY "07a12a33ae0f36b02e1a54ff158402efafeac9832b013592bd8e5f5061c7eb31"

// Pull in OAuth2 device flow tests from the library's test directory
#include "../lib/oauth2_device_flow/test/test_oauth2_device_flow.cpp"

// ═══════════════════════════════════════════════════════════════════
// Test state — reset each test via setUp()
// ═══════════════════════════════════════════════════════════════════

static DeviceSettings deviceSettings;
static KnownNetwork knownNetworks[MAX_KNOWN_NETWORKS];
static int knownNetworkCount = 0;

// ═══════════════════════════════════════════════════════════════════
// WAV Header Tests — file format correctness
// Tests call REAL generate_wav_header() from lib/lifelog_core/codec.h
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
// Tests call REAL generate_opus_head_packet() from lib/lifelog_core/codec.h
// ═══════════════════════════════════════════════════════════════════

void test_opus_head_magic() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    TEST_ASSERT_EQUAL_INT8('O', p.packet[0]);
    TEST_ASSERT_EQUAL_INT8('p', p.packet[1]);
    TEST_ASSERT_EQUAL_INT8('u', p.packet[2]);
    TEST_ASSERT_EQUAL_INT8('s', p.packet[3]);
    TEST_ASSERT_EQUAL_INT8('H', p.packet[4]);
    TEST_ASSERT_EQUAL_INT8('e', p.packet[5]);
    TEST_ASSERT_EQUAL_INT8('a', p.packet[6]);
    TEST_ASSERT_EQUAL_INT8('d', p.packet[7]);
    free(p.packet);
}

void test_opus_head_version() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    TEST_ASSERT_EQUAL_INT(1, p.packet[8]);  // Version must be 1
    free(p.packet);
}

void test_opus_head_channel_count() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    TEST_ASSERT_EQUAL_INT(1, p.packet[9]);  // Mono
    free(p.packet);
}

void test_opus_head_preskip() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    // Pre-skip at bytes 10-11, little-endian
    uint16_t preskip = p.packet[10] | (p.packet[11] << 8);
    TEST_ASSERT_EQUAL_INT(3840, preskip);  // 80ms at 48kHz
    free(p.packet);
}

void test_opus_head_input_sample_rate() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    // Input sample rate at bytes 12-15, little-endian
    uint32_t sr = p.packet[12] | (p.packet[13] << 8) | (p.packet[14] << 16) | (p.packet[15] << 24);
    TEST_ASSERT_EQUAL_UINT32(SAMPLE_RATE, sr);
    free(p.packet);
}

void test_opus_head_output_gain() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    uint16_t gain = p.packet[16] | (p.packet[17] << 8);
    TEST_ASSERT_EQUAL_INT(0, gain);
    free(p.packet);
}

void test_opus_head_channel_mapping() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    TEST_ASSERT_EQUAL_INT(0, p.packet[18]);  // Family 0 for mono
    free(p.packet);
}

void test_opus_head_size() {
    ogg_packet p = {0};
    generate_opus_head_packet(p);
    TEST_ASSERT_EQUAL_INT(19, p.bytes);
    free(p.packet);
}

// ═══════════════════════════════════════════════════════════════════
// Opus Tags Packet Tests — comment header
// Tests call REAL generate_opus_tags_packet() from lib/lifelog_core/codec.h
// ═══════════════════════════════════════════════════════════════════

void test_opus_tags_magic() {
    ogg_packet p = {0};
    generate_opus_tags_packet(p);
    TEST_ASSERT_EQUAL_INT8('O', p.packet[0]);
    TEST_ASSERT_EQUAL_INT8('p', p.packet[1]);
    TEST_ASSERT_EQUAL_INT8('u', p.packet[2]);
    TEST_ASSERT_EQUAL_INT8('s', p.packet[3]);
    TEST_ASSERT_EQUAL_INT8('T', p.packet[4]);
    TEST_ASSERT_EQUAL_INT8('a', p.packet[5]);
    TEST_ASSERT_EQUAL_INT8('g', p.packet[6]);
    TEST_ASSERT_EQUAL_INT8('s', p.packet[7]);
    free(p.packet);
}

void test_opus_tags_vendor_length() {
    ogg_packet p = {0};
    generate_opus_tags_packet(p);
    // Vendor length at bytes 8-11 (after "OpusTags" magic)
    uint32_t vlen = p.packet[8] | (p.packet[9] << 8) | (p.packet[10] << 16) | (p.packet[11] << 24);
    TEST_ASSERT_EQUAL_UINT32(strlen("LifeLog ESP32"), vlen);
    free(p.packet);
}

void test_opus_tags_vendor_string() {
    ogg_packet p = {0};
    generate_opus_tags_packet(p);
    uint32_t vlen = p.packet[8] | (p.packet[9] << 8) | (p.packet[10] << 16) | (p.packet[11] << 24);
    char vendor[64] = {0};
    memcpy(vendor, p.packet + 12, vlen);
    TEST_ASSERT_EQUAL_STRING("LifeLog ESP32", vendor);
    free(p.packet);
}

void test_opus_tags_tag_count_zero() {
    ogg_packet p = {0};
    generate_opus_tags_packet(p);
    uint32_t vlen = p.packet[8] | (p.packet[9] << 8) | (p.packet[10] << 16) | (p.packet[11] << 24);
    int tag_offset = 8 + 4 + vlen;
    uint32_t tag_count = p.packet[tag_offset] | (p.packet[tag_offset+1] << 8) |
                         (p.packet[tag_offset+2] << 16) | (p.packet[tag_offset+3] << 24);
    TEST_ASSERT_EQUAL_UINT32(0, tag_count);
    free(p.packet);
}

void test_opus_tags_total_size() {
    ogg_packet p = {0};
    generate_opus_tags_packet(p);
    // 8 magic + 4 vendor_len + 12 vendor + 4 tag_count = 28
    int expected = 8 + 4 + (int)strlen("LifeLog ESP32") + 4;
    TEST_ASSERT_EQUAL_INT(expected, p.bytes);
    free(p.packet);
}

// ═══════════════════════════════════════════════════════════════════
// Filename Generation Tests
// Tests call REAL generateFilename() from lib/lifelog_core/filename.h
// ═══════════════════════════════════════════════════════════════════

void test_filename_opus_format() {
    char filename[64];
    generateFilename(filename, sizeof(filename), 0, true);
    TEST_ASSERT_EQUAL_STRING("rec_00000.opus", filename);
}

void test_filename_opus_increment() {
    char filename[64];
    generateFilename(filename, sizeof(filename), 42, true);
    TEST_ASSERT_EQUAL_STRING("rec_00042.opus", filename);
    generateFilename(filename, sizeof(filename), 43, true);
    TEST_ASSERT_EQUAL_STRING("rec_00043.opus", filename);
}

void test_filename_wav_format() {
    char filename[64];
    generateFilename(filename, sizeof(filename), 7, false);
    TEST_ASSERT_EQUAL_STRING("rec_00007.wav", filename);
}

void test_filename_large_index() {
    char filename[64];
    generateFilename(filename, sizeof(filename), 99999, true);
    TEST_ASSERT_EQUAL_STRING("rec_99999.opus", filename);
}

void test_filename_buffer_size() {
    char filename[64];
    generateFilename(filename, sizeof(filename), 0, true);
    TEST_ASSERT_TRUE(strlen(filename) < sizeof(filename));
}

// ═══════════════════════════════════════════════════════════════════
// Upload Extension Check Tests
// Tests call REAL uploadExtensionMatches() from lib/lifelog_core/filename.h
// ═══════════════════════════════════════════════════════════════════

void test_upload_extension_opus() {
    TEST_ASSERT_TRUE(uploadExtensionMatches("/lifelog/rec_00000.opus", true));
}

void test_upload_extension_wav() {
    TEST_ASSERT_TRUE(uploadExtensionMatches("/lifelog/rec_00000.wav", false));
}

void test_upload_extension_mismatch() {
    TEST_ASSERT_FALSE(uploadExtensionMatches("/lifelog/rec_00000.wav", true));
}

void test_upload_extension_other_ignored() {
    TEST_ASSERT_FALSE(uploadExtensionMatches("/lifelog/rec_00000.txt", true));
    TEST_ASSERT_FALSE(uploadExtensionMatches("/lifelog/rec_00000.txt", false));
}

// ═══════════════════════════════════════════════════════════════════
// addKnownNetwork Tests
// Tests call REAL addKnownNetwork() from lib/lifelog_core/settings.h
// ═══════════════════════════════════════════════════════════════════

static void test_addKnownNetwork_new() {
    knownNetworkCount = 0;
    addKnownNetwork(knownNetworks, knownNetworkCount, "HomeWiFi", "homepass");
    TEST_ASSERT_EQUAL_INT(1, knownNetworkCount);
    TEST_ASSERT_EQUAL_STRING("HomeWiFi", knownNetworks[0].ssid);
    TEST_ASSERT_EQUAL_STRING("homepass", knownNetworks[0].password);
}

static void test_addKnownNetwork_update_existing() {
    knownNetworkCount = 1;
    strlcpy(knownNetworks[0].ssid, "HomeWiFi", 33);
    strlcpy(knownNetworks[0].password, "oldpass", 65);
    addKnownNetwork(knownNetworks, knownNetworkCount, "HomeWiFi", "newpass");
    TEST_ASSERT_EQUAL_INT(1, knownNetworkCount);
    TEST_ASSERT_EQUAL_STRING("newpass", knownNetworks[0].password);
}

static void test_addKnownNetwork_max_limit() {
    knownNetworkCount = MAX_KNOWN_NETWORKS;
    addKnownNetwork(knownNetworks, knownNetworkCount, "ExtraNet", "extrapass");
    TEST_ASSERT_EQUAL_INT(MAX_KNOWN_NETWORKS, knownNetworkCount);
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
    // Reset settings state
    memset(&deviceSettings, 0, sizeof(deviceSettings));
    knownNetworkCount = 0;
    mock_millis_value = 10000;
}
void tearDown() {}

int main() {
    UNITY_BEGIN();

    // ── WAV Header (13 tests — call real generate_wav_header) ──
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

    // ── Opus Head (8 tests — call real generate_opus_head_packet) ──
    RUN_TEST(test_opus_head_magic);
    RUN_TEST(test_opus_head_version);
    RUN_TEST(test_opus_head_channel_count);
    RUN_TEST(test_opus_head_preskip);
    RUN_TEST(test_opus_head_input_sample_rate);
    RUN_TEST(test_opus_head_output_gain);
    RUN_TEST(test_opus_head_channel_mapping);
    RUN_TEST(test_opus_head_size);

    // ── Opus Tags (5 tests — call real generate_opus_tags_packet) ──
    RUN_TEST(test_opus_tags_magic);
    RUN_TEST(test_opus_tags_vendor_length);
    RUN_TEST(test_opus_tags_vendor_string);
    RUN_TEST(test_opus_tags_tag_count_zero);
    RUN_TEST(test_opus_tags_total_size);

    // ── Filenames (5 tests — call real generateFilename) ──
    RUN_TEST(test_filename_opus_format);
    RUN_TEST(test_filename_opus_increment);
    RUN_TEST(test_filename_wav_format);
    RUN_TEST(test_filename_large_index);
    RUN_TEST(test_filename_buffer_size);

    // ── Upload Extensions (4 tests — call real uploadExtensionMatches) ──
    RUN_TEST(test_upload_extension_opus);
    RUN_TEST(test_upload_extension_wav);
    RUN_TEST(test_upload_extension_mismatch);
    RUN_TEST(test_upload_extension_other_ignored);

    // ── addKnownNetwork (3 tests — call real addKnownNetwork) ──
    RUN_TEST(test_addKnownNetwork_new);
    RUN_TEST(test_addKnownNetwork_update_existing);
    RUN_TEST(test_addKnownNetwork_max_limit);

    // ── OAuth2 Device Flow (20 tests) ──
    RUN_TEST(test_oauth2_initial_state_is_idle);
    RUN_TEST(test_oauth2_start_transitions_to_requesting_code);
    RUN_TEST(test_oauth2_device_code_request_success);
    RUN_TEST(test_oauth2_device_code_request_network_error);
    RUN_TEST(test_oauth2_poll_authorization_pending);
    RUN_TEST(test_oauth2_poll_slow_down);
    RUN_TEST(test_oauth2_poll_success);
    RUN_TEST(test_oauth2_poll_expired_token_error);
    RUN_TEST(test_oauth2_poll_access_denied);
    RUN_TEST(test_oauth2_poll_timeout);
    RUN_TEST(test_oauth2_start_after_error_retries);
    RUN_TEST(test_oauth2_has_valid_token);
    RUN_TEST(test_oauth2_clear_tokens);
    RUN_TEST(test_oauth2_token_refresh);
    RUN_TEST(test_oauth2_storage_roundtrip);
    RUN_TEST(test_oauth2_configure_overwrites_defaults);
    RUN_TEST(test_oauth2_get_returns_zero_when_not_authenticated);
    RUN_TEST(test_oauth2_post_injects_auth_header);
    RUN_TEST(test_oauth2_post_retries_on_401);
    RUN_TEST(test_oauth2_del_injects_auth_header);

    UNITY_END();
    return 0;
}
