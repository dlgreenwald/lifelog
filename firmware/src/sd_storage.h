#pragma once
#include <Arduino.h>
#include "opus_encoder.h"

void initSDStorage();
void saveToSD(OpusFrame frame);
void flushSDQueue();
bool sdHasPendingFiles();
