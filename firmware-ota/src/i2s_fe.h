#pragma once
#include <Arduino.h>

// I2S + AFE public interface (i2s_fe.cpp)
void i2sFeInit();
void afeFeedTask(void *pvParameters);
void afeFetchTask(void *pvParameters);
uint32_t getDmaPartialCount();
