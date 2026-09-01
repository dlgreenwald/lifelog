#pragma once
// Stub of FreeRTOS semaphore header — recursive take/give are mocked in
// mocks.h; only the prototypes are needed so led.cpp parses.

// Real implementations live in test/mocks.h as inline functions returning pdTRUE.
inline BaseType_t xSemaphoreTakeRecursive(SemaphoreHandle_t, TickType_t);
inline BaseType_t xSemaphoreGiveRecursive(SemaphoreHandle_t);

#include "FreeRTOS.h"
