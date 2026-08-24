#pragma once
// Pure business logic for filename generation and extension matching.
// Zero Arduino dependencies.

#include <cstdint>
#include <cstdio>
#include <cstring>

// Generate a recording filename like "rec_00042.opus" or "rec_00042.wav".
inline void generateFilename(char* buf, size_t len, uint32_t index, bool isOpus) {
    snprintf(buf, len, "rec_%05lu.%s", (unsigned long)index, isOpus ? "opus" : "wav");
}

// Check if a filename has the expected extension.
inline bool uploadExtensionMatches(const char* filename, bool expectOpus) {
    const char* dot = strrchr(filename, '.');
    if (!dot) return false;
    return (expectOpus && strcmp(dot, ".opus") == 0) ||
           (!expectOpus && strcmp(dot, ".wav") == 0);
}
