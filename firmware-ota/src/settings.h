#pragma once
// Settings — delegates to lib/lifelog_core/settings.h
// Keep this file for ESP32 builds that include "settings.h" directly.
#include <Arduino.h>
#include "lifelog_core/settings.h"

extern DeviceSettings deviceSettings;
extern KnownNetwork knownNetworks[MAX_KNOWN_NETWORKS];
extern int knownNetworkCount;
