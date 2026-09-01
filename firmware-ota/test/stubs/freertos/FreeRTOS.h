#pragma once
// Minimal FreeRTOS header stub for native tests — supplies the macros/types
// led.cpp references (BaseType_t, pdMS_TO_TICKS) without a real RTOS.

#include <stdint.h>

typedef int32_t BaseType_t;
typedef uint32_t TickType_t;

#define pdTRUE 1
#define pdFALSE 0
#define portMAX_DELAY 0xFFFFFFFF
#define pdMS_TO_TICKS(ms) ((TickType_t)(ms))

// semphr.h is included by led.cpp alongside this header; provide just-enough.
typedef void* SemaphoreHandle_t;
