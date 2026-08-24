#pragma once
// Pure business logic for audio header generation.
// Zero Arduino dependencies. OGG types provided by caller:
//   - ESP32: audio.cpp includes <ogg/ogg.h> before this header
//   - Native tests: mocks.h included before this header

#include <cstdint>
#include <cstring>

#ifndef SAMPLE_RATE
#define SAMPLE_RATE 16000
#endif
#define WAV_HEADER_SIZE 44
#define SAMPLE_BITS 16

// Generate a 44-byte WAV header for PCM audio.
inline void generate_wav_header(uint8_t *wav_header, uint32_t wav_size, uint32_t sample_rate) {
    uint32_t file_size = wav_size + WAV_HEADER_SIZE - 8;
    uint32_t byte_rate = sample_rate * SAMPLE_BITS / 8;

    const uint8_t set_wav_header[] = {
        'R', 'I', 'F', 'F', // ChunkID
        file_size, file_size >> 8, file_size >> 16, file_size >> 24, // ChunkSize
        'W', 'A', 'V', 'E', // Format
        'f', 'm', 't', ' ', // Subchunk1ID
        0x10, 0, 0, 0, // Subchunk1Size (16 for PCM)
        0x01, 0, // AudioFormat (PCM)
        0x01, 0, // NumChannels (mono)
        sample_rate, sample_rate >> 8, sample_rate >> 16, sample_rate >> 24, // SampleRate
        byte_rate, byte_rate >> 8, byte_rate >> 16, byte_rate >> 24, // ByteRate
        0x02, 0, // BlockAlign
        0x10, 0, // BitsPerSample
        'd', 'a', 't', 'a', // Subchunk2ID
        wav_size, wav_size >> 8, wav_size >> 16, wav_size >> 24 // Subchunk2Size
    };

    memcpy(wav_header, set_wav_header, WAV_HEADER_SIZE);
}

// Build OpusHead identification header (RFC 7845).
// Writes into the provided ogg_packet (caller owns memory).
inline void generate_opus_head_packet(ogg_packet &out) {
    uint8_t header[19] = {0};
    // Magic bytes
    header[0] = 'O'; header[1] = 'p'; header[2] = 'u'; header[3] = 's';
    header[4] = 'H'; header[5] = 'e'; header[6] = 'a'; header[7] = 'd';
    header[8] = 1;            // Version
    header[9] = 1;            // Channel count (mono)
    header[10] = 0; header[11] = 15; // Pre-skip: 3840 samples (80ms at 48kHz) little-endian
    header[12] = (uint8_t)(SAMPLE_RATE);
    header[13] = (uint8_t)(SAMPLE_RATE >> 8);
    header[14] = (uint8_t)(SAMPLE_RATE >> 16);
    header[15] = (uint8_t)(SAMPLE_RATE >> 24);
    header[16] = 0; header[17] = 0; // Output gain: 0
    header[18] = 0;            // Channel mapping family: 0

    memset(&out, 0, sizeof(out));
    out.packet = (unsigned char*)malloc(19);
    memcpy(out.packet, header, 19);
    out.bytes = 19;
}

// Build OpusTags comment header (RFC 7845).
// Writes into the provided ogg_packet (caller owns memory).
inline void generate_opus_tags_packet(ogg_packet &out) {
    const char *vendor = "LifeLog ESP32";
    uint32_t vendor_len = strlen(vendor);
    uint32_t tag_data_len = 8 + 4 + vendor_len + 4; // magic + vendor_len + vendor + tag_count(0)
    uint8_t *tag_buf = (uint8_t*)malloc(tag_data_len);

    // "OpusTags" magic
    tag_buf[0] = 'O'; tag_buf[1] = 'p'; tag_buf[2] = 'u'; tag_buf[3] = 's';
    tag_buf[4] = 'T'; tag_buf[5] = 'a'; tag_buf[6] = 'g'; tag_buf[7] = 's';
    // Vendor string length (little-endian)
    tag_buf[8]  = (uint8_t)(vendor_len);
    tag_buf[9]  = (uint8_t)(vendor_len >> 8);
    tag_buf[10] = (uint8_t)(vendor_len >> 16);
    tag_buf[11] = (uint8_t)(vendor_len >> 24);
    // Vendor string
    memcpy(tag_buf + 12, vendor, vendor_len);
    // Tag count = 0
    tag_buf[12 + vendor_len] = 0;
    tag_buf[12 + vendor_len + 1] = 0;
    tag_buf[12 + vendor_len + 2] = 0;
    tag_buf[12 + vendor_len + 3] = 0;

    memset(&out, 0, sizeof(out));
    out.packet = tag_buf;
    out.bytes = tag_data_len;
}
