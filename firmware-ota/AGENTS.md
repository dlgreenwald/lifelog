# Firmware-OTA Agent Guide

## ⚠️ Documentation Sync Rule

**When making changes to any aspect documented in this file (architecture, task model, pin assignments, audio settings, build commands, model partition, test counts, etc.), you MUST update this AGENTS.md to reflect the change.** Stale docs cause agents to make wrong assumptions. Treat this file as code — if it's wrong, fix it in the same change.

## Project Overview

ESP32-S3 firmware for the LifeLog wearable audio recorder. Captures audio via PDM mic, processes it through esp-sr AFE (noise suppression + VAD), encodes to Opus/OGG, stores on SD card, and uploads to the LifeLog server over WiFi.

**Hardware**: Seeed XIAO ESP32-S3 Sense (8MB flash, 8MB PSRAM, built-in PDM mic + SD slot)

## Architecture

### Audio Pipeline

```
PDM Mic (GPIO42 CLK, GPIO41 DIN)
  → I2S Driver (PDM, 16kHz, 16-bit mono, DMA: 4×1024)
  → afeFeedTask [Core 0, 8KB stack]
      i2s_read() → afe_handle->feed()
  → esp-sr AFE Pipeline (AFE_TYPE_VC, LOW_COST)
      WebRTC VAD + NSNET2 noise suppression + AGC
  → afeFetchTask [Core 1, 8KB stack]
      processAfeResult() → VAD state machine → ring buffer
  → writerTask [Core 1, 48KB stack]
      ring buffer → Opus encode → OGG mux → SD file
  → uploadWorkerTask [Core 1, 8KB stack]
      HTTP POST multipart → server → delete file
```

### FreeRTOS Tasks

| Task | Core | Stack | Priority | Role |
|---|---|---|---|---|
| `afe_feed` | 0 | 8192 | 5 | I2S DMA reads → AFE feed |
| `afe_fetch` | 1 | 8192 | 5 | AFE fetch → VAD → ring buffer |
| `writer` | 1 | 49152 | 5 | Ring buffer → Opus → SD |
| `uploader` | 1 | 8192 | 1 | Background HTTP uploads |
| `loop` (Arduino) | 1 | default | 1 | OTA, stats logging |

**Core 0**: Only `afe_feed` — keeps I2S DMA off core 1 where SD/WiFi run.
**Core 1**: Everything else — audio processing pipeline and I/O.

### Shared State

| Resource | Type | Guards |
|---|---|---|
| `sdMutex` | Recursive mutex | All SD SPI access (`sdTake()`/`sdGive()`) |
| `ring_mutex` | Mutex | Ring buffer head/tail/used[] |
| `ring_head` / `ring_tail` | `volatile uint32_t` | Ring buffer indexes (16 slots) |
| `ring_used[16]` | `volatile bool[]` | Per-slot data-present flags |
| `recording` | `volatile bool` | VAD state, read by writerTask |
| `utteranceId`, `chunkIndex`, `isFinal` | `volatile` | Utterance metadata |
| `uploadQueue` | FreeRTOS queue (depth 8) | `UploadRequest` structs |

### Ring Buffer
- 16 slots × 512 samples × 2 bytes = 16KB total (512ms at 16kHz)
- Producer: `afeFetchTask` writes slot, advances `ring_head`
- Consumer: `writerTask` reads slot, advances `ring_tail`
- Overflow: oldest slot dropped, `flushDropCount++`

## Key Files

| File | Purpose |
|---|---|
| `src/config.h` | Pin assignments, server config, log levels, Opus settings |
| `src/main.cpp` | Entry point: setup(), loop(), WiFi, OTA, SD mount, task creation |
| `src/audio.cpp` | Core engine: I2S, AFE, ring buffer, Opus/OGG, writer, upload queue |
| `src/audio.h` | Public API: task handles, sdTake/sdGive, utterance globals |
| `src/upload.cpp` | HTTP multipart upload, file streaming, bulk re-upload |
| `src/upload.h` | Public: uploadFile(), uploadAllRecordings() |
| `src/commands.cpp` | Serial command parser: rec, stop, vad, upload, ls, mic |
| `src/commands.h` | Public: commandsInit(), processCommand() |
| `src/afe_stubs.h` | Weak stubs for esp-dl/FFT symbols not in precompiled libs |
| `test/mocks.h` | Complete ESP32/FreeRTOS/Arduino/Opus/OGG mock layer |
| `test/test_all.cpp` | 68 Unity tests across 10 categories |
| `partitions/partitions_ota.csv` | OTA partition table with model partition |

## Development Commands

### Build
```bash
cd firmware-ota
pio run -e xiao_esp32s3          # Build only
pio run -t upload                 # Upload via OTA (requires WiFi)
pio run -t upload --upload-port /dev/ttyACM1  # Upload via USB (needs esptool protocol override)
```

### USB Flash (when OTA unavailable)

**Full clean flash** — bootloader + partitions + firmware + models (4 files):
```bash
# 1. Erase entire flash (wipes everything including WiFi config and models)
esptool.py --chip esp32s3 --port /dev/ttyACM1 erase_flash

# 2. Flash bootloader + partition table + firmware
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash \
    0x0 .pio/build/xiao_esp32s3/bootloader.bin \
    0x8000 .pio/build/xiao_esp32s3/partitions.bin \
    0x10000 .pio/build/xiao_esp32s3/firmware.bin

# 3. Pack and flash models (see Model Partition section)
# ... run packing script first ...
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash 0x610000 \
  .pio/libdeps/xiao_esp32s3/esp-sr/model/srmodels.bin

# 4. Reset device — WiFi config portal will appear on first boot
```

**Firmware-only update** (models preserved):
```bash
# Only if models are already on the device and you're not changing them
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash \
    0x0 .pio/build/xiao_esp32s3/bootloader.bin \
    0x8000 .pio/build/xiao_esp32s3/partitions.bin \
    0x10000 .pio/build/xiao_esp32s3/firmware.bin
```

**⚠️ Port must not be held by serial monitor.** Close `pio device monitor` before flashing.

### Tests
```bash
pio test -e test                  # Run all 68 native tests
```

### Serial Monitor
```bash
pio device monitor                # 115200 baud
```

### WiFi Config
Device creates AP `LifeLog-Setup` on first boot or connection failure. Connect and configure at `http://192.168.4.1`.

## Serial Commands

| Command | Action |
|---|---|
| `rec` | Start 5-second test recording |
| `stop` | Stop current recording |
| `vad` | Toggle VAD mode on/off |
| `upload` | Upload all recordings on SD |
| `ls` | List files in `/lifelog/` |
| `mic` | Toggle mic on/off |

## Configuration

### Pin Assignments

| Pin | Function | Notes |
|---|---|---|
| GPIO 21 | SD CS + LED | **Shared** — LED toggle disabled to avoid bus contention |
| GPIO 42 | I2S PDM CLK | Sense built-in mic |
| GPIO 41 | I2S PDM DIN | Sense built-in mic |

### Audio Settings

| Setting | Value | Source |
|---|---|---|
| Sample rate | 16000 Hz | `SAMPLE_RATE` |
| Opus frame | 20ms (320 samples) | `AUDIO_OPUS_FRAME_MS` |
| Opus bitrate | 24 kbps | `AUDIO_OPUS_BITRATE` |
| Opus complexity | 5 | `AUDIO_OPUS_COMPLEXITY` |
| SD SPI clock | 25 MHz | `SD.begin(SD_CS_PIN, SPI, 25000000)` |

### Server

| Setting | Value |
|---|---|
| Host | `192.168.68.190` |
| Port | `8444` |
| Endpoint | `POST /api/v1/upload` |
| Auth | `X-API-Key` header |

### Compile-Time Flags

| Flag | Effect |
|---|---|
| `-DAUDIO_FORMAT_OPUS` | Enables Opus encoder + OGG mux (current default) |
| `-Wl,--unresolved-symbols=ignore-all` | Allows linking with stubs for missing esp-sr symbols |

### Log Levels

Per-component, compile-time in `config.h` (0=NONE, 1=ERROR, 2=WARN, 3=INFO, 4=DEBUG):
BOOT, WIFI, OTA, SYSTEM, SD, I2S, AUDIO, VAD, AFE, UPLOAD, CMD, MIC, LS

## Partition Table

| Name | Type | Offset | Size |
|---|---|---|---|
| `nvs` | data/nvs | 0x9000 | 20KB |
| `otadata` | data/ota | 0xe000 | 8KB |
| `app0` | app/ota_0 | 0x10000 | 3MB |
| `app1` | app/ota_1 | 0x310000 | 3MB |
| `model` | data/spiffs | 0x610000 | 1.9MB |

**⚠️ The `model` partition is NOT SPIFFS** — it's a raw binary packed by `pack_model.py` and memory-mapped via `esp_partition_mmap`. See [Model Partition](#model-partition) below.

## Model Partition

The `model` partition stores esp-sr models (nsnet2 + multinet) as a packed binary.

### What's needed
- **nsnet2** (330KB) — noise suppression
- **mn4q8_cn** (880KB) — speech command recognition (smallest that fits)
- WakeNet: disabled via weak stubs
- VADNet: disabled (WebRTC fallback)

### Binary format
```
uint32 model_count
For each model:
  char[32] model_name (null-padded)
  uint32 file_count
  For each file:
    char[32] file_name (null-padded)
    uint32 data_offset  (absolute from start)
    uint32 data_size
[data section]
```

### Rebuild (when models are lost after erase_flash)

**Step 1**: Pack the models into a binary blob:
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

**Step 2**: Flash the model binary to the device:
```bash
# Device must NOT have serial monitor open (port lock conflict)
esptool.py --chip esp32s3 --port /dev/ttyACM1 --baud 921600 \
  write_flash 0x610000 \
  .pio/libdeps/xiao_esp32s3/esp-sr/model/srmodels.bin
```

**Step 3**: Reset the device — it will load models via mmap on next boot.

**When models are needed**:
- After `erase_flash` (wipes entire flash including model partition)
- After `pio run -t upload` does NOT need models (only bootloader + partitions + firmware)
- If serial log shows `"esp_srmodel_init failed"` or `"Model partition empty"`

### Pitfalls
- Full `erase_flash` wipes model partition — must reflash after erase
- Upstream `pack_model.py` has a directory walk bug — use the script above
- English multinets (mn5q8_en, mn7_en) are too large for 1.9MB partition
- OTA uploads don't include model partition

## Testing

### ⚠️ Critical Limitation: Tests Are Re-implementations

The test file (`test/test_all.cpp`) does **NOT** `#include` or link against the actual source files (`audio.cpp`, `upload.cpp`, etc.). Instead, it **re-implements** each function being tested from scratch. The comment in the test file says:

> "Functions under test (re-implemented from audio.cpp) — These match the source exactly. Tests verify correctness of the algorithm, not a copy — the source uses the same math."

**This means tests can pass while the real code has bugs.** If you change `audio.cpp` and don't update `test_all.cpp`, the tests still pass because they test the old re-implementation, not your changes. Treat these tests as algorithm specification verification, not regression tests.

To fix this properly: restructure tests to `#include` the actual `.cpp` files (with appropriate mocks), or use PlatformIO's `test_build_src = true` to compile source files into the test binary.

### Framework
- **Unity** (throwtheswitch/Unity@^2.5.2) — native platform, no hardware needed
- **68 tests** across 10 categories

### Categories
WAV header generation, Opus header generation, Opus frame encoding, OGG page structure, ring buffer operations, VAD state machine, file naming, upload request building, command parsing, config validation

### Mock Layer (`test/mocks.h`)
Complete ESP32/FreeRTOS/Arduino mock for native compilation:
- FreeRTOS: queues, mutexes, tasks, notifications, delays
- Arduino: Serial, GPIO, millis/micros
- I2S: driver mocks
- esp-sr AFE: mock pipeline with configurable VAD state
- Opus: encoder that passes through frame count
- OGG: libogg mocks (ogg_stream_init, ogg_stream_packetin, ogg_stream_pageout)
- SD: file system mock with in-memory directory

### Running
```bash
pio test -e test
```

## Error Handling

### Boot Rollback
- `bootInit()` checks NVS `confirmed` flag and `boots` counter
- OTA start resets both to 0
- If `boots > MAX_BOOT (3)` and unconfirmed → device stays in current state
- `bootConfirm()` called after successful `setup()`

### Watchdog
- ESP task WDT enabled by default
- After setup: loop task and idle task removed from WDT
- AFE tasks yield via 100ms `i2s_read` timeouts

### AFE Failure
- Tasks check `afe_handle`/`afe_data` at start; if NULL, self-delete
- `afeInit()` logs and returns without crashing on any failure

### Ring Buffer Overflow
- Oldest slot dropped, `flushDropCount++`, logged as warning

### SD Failures
- Mount failure logged, SD unavailable (no retry)
- File open failure returns null/false

### Upload Failures
- Single attempt; file stays on SD on failure
- Queue full (depth 8): file skipped
- WiFi not connected: upload skipped silently

## Build Scripts

| Script | Steps |
|---|---|
| `build.sh` | pio compile → native tests (88 tests) |

## Dependencies

| Library | Version | Purpose |
|---|---|---|
| `tzapu/WiFiManager` | ^2.0.17 | Captive portal WiFi setup |
| `sh123/esp32_opus` | ^1.0.3 | Opus encoder |
| `pschatzmann/codec-ogg` | GitHub HEAD | OGG container mux |
| `espressif/esp-sr` | Commit `4f1b5607` | Speech recognition (AFE, NSNET2) |

Linked esp-sr libs: `esp_audio_front_end`, `esp_audio_processor`, `dl_lib`, `vadnet`, `nsnet`, `c_speech_features`, `fst`, `hufzip`, `multinet`, `wakenet`

## Common Pitfalls

1. **GPIO 21 conflict**: LED and SD CS share pin 21. LED toggle code is commented out — never re-enable without resolving bus contention.
2. **SD SPI and I2S DMA share FSPI bus**: Writing to SD while I2S is actively streaming causes card errors. Solution: buffer audio in RAM first, write after recording stops.
3. **OGG granulepos**: Must be in 48kHz units (`frame_size × 48000 / 16kHz`), not sample count.
4. **Opus pre-skip**: 3840 samples (80ms at 48kHz) per RFC 7845 — affects playback sync.
5. **File index persists in RAM only**: Lost on reboot, may reuse filenames. Use `upload` command to clear old files.
6. **OTA protocol**: `platformio.ini` defaults to `espota`. USB flash requires `esptool.py` directly with correct offsets (0x0, 0x8000, 0x10000, 0x610000).
7. **Model partition not SPIFFS**: Despite `data, spiffs` type, it's memory-mapped raw binary. Don't use SPIFFS API.
