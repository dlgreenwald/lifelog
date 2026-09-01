#pragma once
// Minimal Arduino.h stub for native tests — types/constants config.h expects.
// The full Arduino stdlib isn't available; anything beyond what's defined here
// must be stubbed at the call site in test/.

#include <stdint.h>
#include <stdlib.h>

#ifndef HIGH
#define HIGH 1
#endif
#ifndef LOW
#define LOW 0
#endif
#ifndef LED_BUILTIN
#define LED_BUILTIN 13
#endif

// Arduino's print class is mocked elsewhere in this TU.
