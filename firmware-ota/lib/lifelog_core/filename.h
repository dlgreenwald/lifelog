#pragma once
// Pure business logic for filename generation and extension matching.
// Zero Arduino dependencies.

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>

// Generate a recording filename like "rec_00042.opus" or "rec_00042.wav".
inline void generateFilename(char* buf, size_t len, uint32_t index, bool isOpus) {
    snprintf(buf, len, "rec_%05lu.%s", (unsigned long)index, isOpus ? "opus" : "wav");
}

// "20250907T143052_042.opus" — UTC timestamp + per-second monotonic index
inline void generateFilenameUtc(char* buf, size_t len, time_t utc_epoch, uint32_t index, bool isOpus) {
    struct tm tm_utc;
    gmtime_r(&utc_epoch, &tm_utc);
    strftime(buf, len, "%Y%m%dT%H%M%S", &tm_utc);
    snprintf(buf + strlen(buf), len - strlen(buf), "_%03lu.%s",
             (unsigned long)index % 1000, isOpus ? "opus" : "wav");
}

// Check if a filename has the expected extension.
inline bool uploadExtensionMatches(const char* filename, bool expectOpus) {
    const char* dot = strrchr(filename, '.');
    if (!dot) return false;
    return (expectOpus && strcmp(dot, ".opus") == 0) ||
           (!expectOpus && strcmp(dot, ".wav") == 0);
}
