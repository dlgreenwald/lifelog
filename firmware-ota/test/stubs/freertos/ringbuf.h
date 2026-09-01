#pragma once
// Minimal freertos/ringbuf.h stub for native tests — only types needed for
// led.cpp's transitive include of audio.h. The actual ring buffer producers
// (i2s_fe.cpp, writer.cpp) are NOT pulled into test/led.cpp's TU; nothing
// here needs real RTOS ring buffer semantics.

#include <stdint.h>
#include <stddef.h>

typedef void* RingbufHandle_t;

// Stubs so audio.h's declaration compiles; the test TU never calls them
// (audio.cpp is not included — its symbols are provided directly in test_led.cpp).
static inline uint32_t vRingbufferGetInfo(void* a, void* b, void* c, void* d, void* e, void* f) { return 0; }
