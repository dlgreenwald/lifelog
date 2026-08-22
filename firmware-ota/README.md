# LifeLog Firmware (ESP32-S3)

Firmware for the LifeLog wearable audio recorder. Captures audio via the built-in PDM microphone, processes it through esp-sr for noise suppression and voice activity detection, encodes to Opus/OGG, stores on SD card, and uploads to the LifeLog server over WiFi.

See [ARCHITECTURE.md](ARCHITECTURE.md) for a deep-dive into the FreeRTOS task model, audio pipeline, shared state, and PlantUML diagrams.

## Hardware

| Component | Part | Notes |
|-----------|------|-------|
| Board | [XIAO ESP32-S3 Sense](https://www.seeedstudio.com/XIAO-ESP32S3-Microcontroller-v2-0-p-5853.html) | 8MB PSRAM, 8MB flash, built-in PDM mic + SD slot |
| Microphone | Built-in PDM mic | No external wiring needed |
| SD Card | SPI mode | Built-in slot |
| Battery | 400mAh LiPo | ~11 hours with VAD |

### Pin Assignments

| Pin | Function | Notes |
|-----|----------|-------|
| GPIO 42 | I2S PDM CLK | Built-in mic |
| GPIO 41 | I2S PDM DIN | Built-in mic |
| GPIO 21 | SD CS + LED | **Shared** — LED toggle disabled to avoid bus contention |

### SD Card (built-in slot)

| Signal | GPIO |
|--------|------|
| CS | 21 |
| MOSI | 38 |
| MISO | 39 |
| SCLK | 40 |
| VCC | 3.3V |
| GND | GND |

## Prerequisites

- [PlatformIO](https://platformio.org/) (`pip install platformio`)
- USB cable for initial flash (OTA updates over WiFi thereafter)

## Build

```bash
cd firmware-ota

# Build only
pio run

# Build for native test environment
pio run -e test
```

## Flash

### Via OTA (recommended after initial flash)

Requires the device to be on the same network and previously configured with WiFi.

```bash
pio run -t upload
```

### Via USB

When OTA is unavailable (first flash, or OTA failed):

```bash
# Firmware only (bootloader + partitions + app)
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash \
    0x0 .pio/build/xiao_esp32s3/bootloader.bin \
    0x8000 .pio/build/xiao_esp32s3/partitions.bin \
    0x10000 .pio/build/xiao_esp32s3/firmware.bin
```

### Full clean flash (includes models)

```bash
# 1. Erase everything
esptool.py --chip esp32s3 --port /dev/ttyACM1 erase_flash

# 2. Flash bootloader + partitions + firmware
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash \
    0x0 .pio/build/xiao_esp32s3/bootloader.bin \
    0x8000 .pio/build/xiao_esp32s3/partitions.bin \
    0x10000 .pio/build/xiao_esp32s3/firmware.bin

# 3. Pack and flash models (see Model Partition section below)
# 4. Reset device — WiFi config portal appears on first boot
```

## Configuration

Edit `src/config.h` before building:

```cpp
// Server connection
#define SERVER_HOST    "192.168.68.190"
#define SERVER_PORT    8444
#define SERVER_PATH    "/api/v1/upload"
#define API_KEY        "your-api-key-here"
```

### Audio Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `AUDIO_OPUS_FRAME_MS` | 20 | Opus frame size (ms) |
| `AUDIO_OPUS_BITRATE` | 24000 | Opus bitrate (bps) |
| `AUDIO_OPUS_COMPLEXITY` | 5 | CPU/quality tradeoff (0-10) |

### Log Levels

Per-component, compile-time in `config.h` (0=NONE, 1=ERROR, 2=WARN, 3=INFO, 4=DEBUG):

| Component | Default |
|-----------|---------|
| BOOT | INFO |
| WIFI | INFO |
| OTA | INFO |
| SYSTEM | WARN |
| SD | DEBUG |
| I2S | INFO |
| AUDIO | INFO |
| VAD | INFO |
| AFE | INFO |
| UPLOAD | INFO |
| CMD | DEBUG |
| MIC | DEBUG |

## WiFi Setup

On first boot (or after connection failure), the device creates a captive portal AP:

- **SSID**: `LifeLog-Setup`
- **URL**: `http://192.168.4.1`

Connect and configure your WiFi credentials. The device saves them to NVS and auto-reconnects on subsequent boots.

## Serial Commands

Connect via serial monitor (115200 baud):

```bash
pio device monitor
```

| Command | Action |
|---------|--------|
| `rec` | Start 5-second test recording |
| `stop` | Stop current recording |
| `vad` | Toggle VAD mode on/off |
| `upload` | Upload all recordings on SD |
| `ls` | List files in `/lifelog/` |
| `mic` | Toggle mic on/off |

## Testing

Run native tests (no hardware required):

```bash
pio test -e test
```

108 tests across 10 categories: audio encoding, OGG container, ring buffer, upload protocol, VAD logic, SD card operations, FreeRTOS synchronization, boot sequence, configuration, and command parsing.

See [AGENTS.md](AGENTS.md) for details on the test mock layer and what's tested vs. not tested.

## Model Partition

The `model` partition stores esp-sr models (nsnet2 + multinet) as a packed binary. It's memory-mapped at boot — not SPIFFS.

### When models are needed

- After `erase_flash` (wipes entire flash)
- If serial log shows `"esp_srmodel_init failed"`
- NOT needed for firmware-only updates (`pio run -t upload`)

### Rebuild models

```bash
cd firmware-ota
python3 -c "
import struct, os
MODEL_DIR = '.pio/libdeps/xiao_esp32s3/esp-sr/model'
STR_LEN = 32
def pack_string(s):
    b = s.encode('utf-8')[:STR_LEN]
    return b + b'\x00' * (STR_LEN - len(b))
needed = {
    'nsnet2': os.path.join(MODEL_DIR, 'nsnet_model/nsnet2'),
    'mn4q8_cn': os.path.join(MODEL_DIR, 'multinet_model/mn4q8_cn'),
}
models = {}
for name, path in needed.items():
    files = {}
    for f in sorted(os.listdir(path)):
        fp = os.path.join(path, f)
        if os.path.isfile(fp):
            with open(fp, 'rb') as fh:
                files[f] = fh.read()
    if files: models[name] = files
file_count = sum(len(v) for v in models.values())
header_size = 4 + len(models) * (STR_LEN + 4) + file_count * (STR_LEN + 4 + 4)
data_offsets = {}
current_offset = header_size
for name in sorted(models.keys()):
    for fname in sorted(models[name].keys()):
        data_offsets[(name, fname)] = current_offset
        current_offset += len(models[name][fname])
out = struct.pack('I', len(models))
for name in sorted(models.keys()):
    out += pack_string(name)
    out += struct.pack('I', len(models[name]))
    for fname in sorted(models[name].keys()):
        out += pack_string(fname)
        out += struct.pack('I', data_offsets[(name, fname)])
        out += struct.pack('I', len(models[name][fname]))
for name in sorted(models.keys()):
    for fname in sorted(models[name].keys()):
        out += models[name][fname]
with open(os.path.join(MODEL_DIR, 'srmodels.bin'), 'wb') as f:
    f.write(out)
print(f'Packed {len(out)/1024:.0f} KB ({len(out)} bytes)')
"
```

### Flash models

```bash
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash 0x610000 \
  .pio/libdeps/xiao_esp32s3/esp-sr/model/srmodels.bin
```

## Partition Table

| Name | Type | Offset | Size |
|------|------|--------|------|
| `nvs` | data/nvs | 0x9000 | 20KB |
| `otadata` | data/ota | 0xe000 | 8KB |
| `app0` | app/ota_0 | 0x10000 | 3MB |
| `app1` | app/ota_1 | 0x310000 | 3MB |
| `model` | data/spiffs | 0x610000 | 1.9MB |

## Dependencies

| Library | Purpose |
|---------|---------|
| `tzapu/WiFiManager` | Captive portal WiFi setup |
| `sh123/esp32_opus` | Opus encoder |
| `pschatzmann/codec-ogg` | OGG container mux |
| `espressif/esp-sr` | AFE (NSNET2 + WebRTC VAD) |

## Documentation

- **[AGENTS.md](AGENTS.md)** — Agent guide: architecture, task model, build commands, common pitfalls
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Deep-dive: FreeRTOS tasks, audio pipeline, shared state, PlantUML diagrams
