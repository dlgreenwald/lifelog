#pragma once
#include <Arduino.h>
#include "opus_encoder.h"

void uploaderTask(void *pvParameters);
bool uploadAudio(OpusFrame frame);
