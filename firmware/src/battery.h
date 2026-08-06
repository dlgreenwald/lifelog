#pragma once
#include <Arduino.h>

void batteryMonitorTask(void *pvParameters);
float readBatteryVoltage();
int voltageToPercent(float voltage);
