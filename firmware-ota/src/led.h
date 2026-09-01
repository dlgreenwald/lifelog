#pragma once
#include <Arduino.h>

// LED — reflects audio pipeline state. Shares GPIO21 with SD CS;
// SD operations preempt LED via sdMutex (taken non-blocking in ledLoop()).
void ledInit();
void ledLoop();
