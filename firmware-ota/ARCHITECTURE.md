# Firmware-OTA Architecture

This document describes the architecture of the ESP32-S3 firmware for the LifeLog wearable audio recorder. It covers the FreeRTOS task model, core assignment, data flow, and shared state.

## System Overview

The firmware runs on a Seeed XIAO ESP32-S3 Sense (dual-core 240MHz, 8MB PSRAM, 8MB flash). Audio is captured from the built-in PDM microphone, processed through esp-sr for noise suppression and voice activity detection, encoded to Opus, stored on the SD card, and uploaded to the LifeLog server over WiFi.

```plantuml
@startuml
skinparam backgroundColor white
skinparam componentStyle rectangle

rectangle "Hardware" {
  component "PDM Mic\n(GPIO 42/41)" as mic
  component "SD Card\n(GPIO 21, SPI 25MHz)" as sd
  component "WiFi\n(ESP32-S3)" as wifi
}

rectangle "Core 0" {
  component "afeFeedTask\n8KB stack, pri=5" as feed
}

rectangle "Core 1" {
  component "afeFetchTask\n8KB stack, pri=5" as fetch
  component "writerTask\n48KB stack, pri=5" as writer
  component "uploadWorkerTask\n8KB stack, pri=1" as uploader
  component "Arduino loop\n(OTA + stats)" as loop
}

rectangle "Shared" {
  component "Ring Buffer\n32 slots × 512 samples" as ring
  component "Upload Queue\n8 slots" as queue
  component "sdMutex\n(Recursive)" as mutex
}

cloud "esp-sr AFE\n(NSNET2 + WebRTC VAD)" as afe
cloud "Opus Encoder\n(24kbps, 20ms frames)" as opus
cloud "Server\n192.168.68.190:8444" as server

mic -down-> feed : I2S DMA\n4×1024 samples
feed -right-> afe : afe_handle->feed()
afe -down-> fetch : afe_handle->fetch()\nNS-cleaned audio + VAD state
fetch -down-> ring : Ring buffer write
ring -down-> writer : Ring buffer read
writer -right-> opus : PCM frames
opus -down-> sd : Opus/OGG files\n(/lifelog/rec_*.opus)
writer -right-> queue : UploadRequest\n(on voice end)
queue -down-> uploader : xQueueReceive
uploader -right-> sd : Read file\n(sdMutex held)
uploader -right-> wifi : HTTP POST
wifi -right-> server : multipart upload

feed -[hidden]right-> fetch
fetch -[hidden]right-> writer
writer -[hidden]right-> uploader

note right of feed
  **Core 0** — isolated I2S reads
  Keeps DMA off core 1 where
  SD and WiFi run
end note

note right of writer
  **Core 1** — all processing + I/O
  Largest stack (48KB) for
  Opus encode + OGG mux
end note
@enduml
```

## Core Assignment

The dual-core ESP32-S3 is split deliberately:

| Core | Tasks | Rationale |
|------|-------|-----------|
| **Core 0** | `afeFeedTask` only | Isolates I2S DMA reads from SD/WiFi contention. DMA and FSPI share internal bus resources — keeping DMA on a separate core prevents bus conflicts. |
| **Core 1** | `afeFetchTask`, `writerTask`, `uploadWorkerTask`, Arduino `loop()` | All audio processing, file I/O, and network operations run here. Tasks yield via timeouts, mutexes, and queue operations so the scheduler can interleave them. |

```plantuml
@startuml
skinparam backgroundColor white

rectangle "Core 0 (CPU0)" as c0 {
  rectangle "afeFeedTask\nPriority: 5\nStack: 8KB" as feed
  note bottom of feed
    Reads I2S PDM mic (100ms timeout)
    Feeds raw audio into AFE pipeline
    Yields to WDT via i2s_read timeout
  end note
}

rectangle "Core 1 (CPU1)" as c1 {
  rectangle "afeFetchTask\nPriority: 5\nStack: 8KB" as fetch
  rectangle "writerTask\nPriority: 5\nStack: 48KB" as writer
  rectangle "uploadWorkerTask\nPriority: 1\nStack: 8KB" as uploader
  rectangle "Arduino loop()\nPriority: 1\nStack: default" as loop
}

feed -right-> fetch : raw audio\n(AFE pipeline)
fetch -down-> writer : ring buffer\nnotification
writer -down-> uploader : upload queue

note bottom of c0
  **Why separate cores?**
  I2S DMA and FSPI (SD card) share
  internal bus resources on ESP32-S3.
  Running DMA on core 0 prevents
  bus contention with SD writes.
end note

note bottom of c1
  **Why core 1 for everything else?**
  - afeFetch needs fast access to ring buffer
  - writer needs Opus encode + SD write
  - uploader is low-priority background work
  - OTA runs in Arduino loop
end note
@enduml
```

## Audio Pipeline

The audio pipeline transforms raw PDM microphone samples into Opus-encoded OGG files on the SD card. OGG pages are first buffered in PSRAM (≥4KB) before opening the SD file, eliminating SD latency during voice onset. Short utterances (<4KB) are discarded without touching SD.

```plantuml
@startuml
skinparam backgroundColor white
skinparam activityFontSize 12

|Core 0|
start
:afeFeedTask;
:i2s_read() — 100ms timeout;
note right: 512 samples × 2 bytes\nDMA: 4×1024 buffers
:afe_handle->feed(raw_audio);
note right: esp-sr AFE pipeline\nprocesses in-place

|Core 1|
:afeFetchTask;
:afe_handle->fetch();
note right
  Returns:
  - NS-cleaned audio (noise suppression)
  - VAD state (voice/none)
  - Wake word detection (disabled)
end note

if (VAD state changed?) then (voice start)
  :Set recording = true;
  :Prepend VAD cache\n(8192 samples pre-trigger);
  :Init OGG stream in memory\n(copy pre-generated headers);
  :xTaskNotifyGive(writerTask);
elseif (voice continued) then
  :Write 512 samples to ring buffer;
  :xTaskNotifyGive(writerTask);
elseif (voice end) then
  :Set recording = false;
  :Write EOS marker to ring buffer;
  :xTaskNotifyGive(writerTask);
else (no change)
endif

:writerTask;
if (ring buffer has data?) then (yes)
  :Read 512 samples from ring buffer;
  :Accumulate into pcm_buf (8KB);
  while (pcm_buf has ≥320 samples?) do (Opus frame)
    :Encode 20ms frame (320 samples);
    :Drain OGG pages to buffer or SD;
    note right
      Before 4KB: buffer in PSRAM
      ≥4KB: open SD file, flush buffer
      After flush: write directly to SD
    end note
  endwhile
else (empty)
  :Wait for ring buffer notification;
endif

if (recording ended?) then (yes)
  if (pages_flushed?) then (yes)
    :Write EOS page;
    :Flush + close file;
    :Queue upload request;
  else (short utterance)
    :Discard buffered pages;
    note right: No SD write for\nutterances <4KB
  endif
else (no)
endif

:uploadWorkerTask;
if (upload queue has request?) then (yes)
  :Read file from SD;
  note right: 4KB chunks\nsdMutex yield between chunks
  :HTTP POST multipart/form-data;
  if (success?) then
    :Delete file from SD;
  else (fail)
    :Log warning, keep file;
  endif
else (empty)
  :vTaskDelay(100ms);
endif

stop
@enduml
```

## Shared State and Synchronization

All shared state between tasks is protected by mutexes or FreeRTOS primitives.

```plantuml
@startuml
skinparam backgroundColor white
skinparam componentStyle rectangle

rectangle "Shared State" {
  rectangle "sdMutex\n(Recursive Mutex)" as sd_mutex
  rectangle "ring_mutex\n(Mutex)" as ring_mutex
  rectangle "uploadQueue\n(FreeRTOS Queue, depth 8)" as upload_q

  rectangle "ring_head\nvolatile uint32_t" as head
  rectangle "ring_tail\nvolatile uint32_t" as tail
  rectangle "ring_used[32]\nvolatile bool[]" as used
  rectangle "recording\nvolatile bool" as recording
  rectangle "utteranceId\nvolatile uint32_t" as utt_id
  rectangle "chunkIndex\nvolatile uint32_t" as chunk_idx
  rectangle "isFinal\nvolatile bool" as is_final
  rectangle "ogg_buf\nPSRAM 16KB" as ogg_buf
  rectangle "pages_flushed\nvolatile bool" as flushed
}

rectangle "afeFetchTask" as fetch
rectangle "writerTask" as writer
rectangle "uploadWorkerTask" as uploader

fetch -right-> ring_mutex : acquires to\nwrite ring buffer
fetch -right-> recording : writes\nVAD state
fetch -right-> utt_id : writes
fetch -right-> chunk_idx : writes
fetch -right-> is_final : writes

writer -down-> ring_mutex : acquires to\nread ring buffer
writer -down-> recording : reads\nVAD state
writer -down-> sd_mutex : acquires for\nSD writes
writer -right-> upload_q : xQueueSend

uploader -left-> sd_mutex : acquires for\nSD reads
uploader -left-> upload_q : xQueueReceive

note bottom of sd_mutex
  **sdMutex** is recursive — allows
  nested locking from upload stream
  chunks (4KB read → release → re-acquire)
end note

note bottom of ring_mutex
  **ring_mutex** guards ring buffer
  head/tail/used[] between
  afeFetchTask (producer) and
  writerTask (consumer)
end note
@enduml
```

### Ring Buffer Detail

The ring buffer decouples the real-time audio capture from the variable-latency SD write and upload operations.

| Property | Value |
|----------|-------|
| Slots | 32 |
| Samples per slot | 512 |
| Bytes per slot | 1024 (512 × 2 bytes) |
| Total size | 32,768 bytes (32KB) |
| Duration | 1024ms at 16kHz |
| Producer | `afeFetchTask` (writes `ring_head`) |
| Consumer | `writerTask` (reads `ring_tail`) |
| Overflow | Oldest slot dropped, `flushDropCount++` |

```plantuml
@startuml
skinparam backgroundColor white

rectangle "Ring Buffer (32 slots)" {
  collections "slot 0" as s0
  collections "slot 1" as s1
  collections "slot 2" as s2
  collections "..." as s3
  collections "slot 31" as s15

  s0 -[hidden]right-> s1
  s1 -[hidden]right-> s2
  s2 -[hidden]right-> s3
  s3 -[hidden]right-> s15
}

rectangle "afeFetchTask\n(Producer)" as producer
rectangle "writerTask\n(Consumer)" as consumer

producer -down-> ring_head : advances
consumer -down-> ring_tail : advances

note as n1
  **Flow:**
  1. afeFetchTask writes to ring_used[ring_head]
  2. Advances ring_head = (ring_head + 1) % 32
  3. Notifies writerTask via xTaskNotifyGive
  4. writerTask reads from ring_used[ring_tail]
  5. Advances ring_tail = (ring_tail + 1) % 32

  **Overflow:**
  If ring_used[next_head] is true (slot not consumed),
  oldest slot is dropped and ring_tail advances.
end note
@enduml
```

## Startup Sequence

```plantuml
@startuml
skinparam backgroundColor white

start
:Serial.begin(115200);
:Delay 1000ms;

:bootInit();
note right: Check NVS boot counter\nand confirmed flag

:setupWiFi();
note right
  WiFiManager captive portal
  AP: LifeLog-Setup
  Timeout: 120s
end note

:setupSD();
note right
  SD.begin(SD_CS_PIN, SPI, 25000000)
  25MHz SPI clock
  Creates /lifelog/ if missing
end note

:audioInit();
note right
  - Init I2S PDM (16kHz, mono)
  - Init esp-sr AFE (NSNET2 + WebRTC VAD)
  - Init Opus encoder (24kbps, 20ms frames)
  - Init OGG mux
  - Create ring buffer
  - Create upload queue (depth 8)
end note

:setupOTA();
note right: ArduinoOTA init\nHostname: lifelog

:commandsInit();
note right: Serial command parser

fork
  :xTaskCreatePinnedToCore\nafe_feed → Core 0;
fork again
  :xTaskCreatePinnedToCore\nafe_fetch → Core 1;
fork again
  :xTaskCreatePinnedToCore\nwriter → Core 1;
end fork

:setWriterTaskHandle();

:esp_task_wdt_delete(NULL);
note right: Remove loop + idle from WDT

:bootConfirm();
note right: NVS: confirmed=1, boots=0

:Log "Ready! AFE active";
stop
@enduml
```

## Opus/OGG Encoding

| Setting | Value |
|---------|-------|
| Codec | Opus (libopus via esp32_opus) |
| Container | OGG (libogg via codec-ogg) |
| Sample rate | 16 kHz (input) → 48 kHz (OGG granulepos) |
| Frame size | 20ms (320 samples at 16kHz) |
| Bitrate | 24 kbps |
| Complexity | 5 (0-10 scale) |
| Signal type | VOIP |
| Pre-skip | 3840 samples (80ms at 48kHz, per RFC 7845) |

**OGG Stream Structure:**
1. OpusHead packet (19 bytes) — stream metadata
2. OpusTags packet (28 bytes) — vendor "LifeLog ESP32"
3. Opus audio packets — encoded frames, pages flushed every ~4KB (~1.3s)
4. EOS (End of Stream) packet — 1-byte body

**Granulepos Calculation:** OGG granulepos is in 48kHz units. For 16kHz input:
```
granulepos += frame_size * 48000 / 16000  // = frame_size * 3
```

## Error Handling

```plantuml
@startuml
skinparam backgroundColor white
skinparam activityFontSize 11

start

partition "Boot Rollback" {
  if (NVS boots > MAX_BOOT (3) AND not confirmed?) then (yes)
    :Stay in current state;
    :Don't run setup();
    note right: Prevents boot loop\nafter bad OTA
  else (no)
    :Proceed with setup();
  endif
}

partition "AFE Failure" {
  if (model partition missing or empty?) then (yes)
    :Log error "AFE disabled";
    :afeFeedTask + afeFetchTask\nself-delete;
    note right: Device still boots\nbut no audio processing
  else (no)
    :Initialize AFE pipeline;
  endif
}

partition "Ring Buffer Overflow" {
  if (ring_used[next_head] is true?) then (yes)
    :Drop oldest slot;
    :flushDropCount++;
    :Advance ring_tail;
    note right: Graceful degradation\n— lose old audio, keep new
  else (no)
    :Write to ring buffer;
  endif
}

partition "SD Failure" {
  if (SD.begin() fails?) then (yes)
    :Log error;
    :SD unavailable;
    note right: No retry — device\ncontinues without storage
  else (no)
    :SD ready;
  endif
}

partition "Upload Failure" {
  if (HTTP POST fails?) then (yes)
    :Log warning;
    :File stays on SD;
    note right: Single attempt\nNo retry — file preserved\nfor later upload
  else (no)
    :Delete file from SD;
  endif
}

partition "Watchdog" {
  note right
    After setup():
    - Loop task removed from WDT
    - Idle task removed from WDT
    - AFE tasks yield via 100ms
      i2s_read timeouts
  end note
}

stop
@enduml
```

## Configuration Reference

### Pin Assignments

| Pin | Function | Notes |
|-----|----------|-------|
| GPIO 21 | SD CS + LED | **Shared** — LED toggle disabled to avoid bus contention |
| GPIO 42 | I2S PDM CLK | Sense built-in mic |
| GPIO 41 | I2S PDM DIN | Sense built-in mic |

### Audio Pipeline Settings

| Setting | Value | Location |
|---------|-------|----------|
| Sample rate | 16,000 Hz | `audio.h` |
| DMA buffers | 4 × 1024 samples | `audio.cpp` |
| Ring buffer slots | 32 | `audio.cpp` |
| Ring buffer chunk | 512 samples (32ms) | `audio.cpp` |
| OGG buffer capacity | 16 KB (PSRAM) | `audio.cpp` |
| OGG flush threshold | 4 KB before SD open | `audio.cpp` |
| Opus frame | 20ms (320 samples) | `config.h` |
| Opus bitrate | 24 kbps | `config.h` |
| Opus complexity | 5 | `config.h` |
| SD SPI clock | 25 MHz | `main.cpp` |
| Upload chunk size | 4 KB | `upload.cpp` |
| Upload queue depth | 8 | `audio.cpp` |

### AFE Configuration

| Setting | Value |
|---------|-------|
| Type | `AFE_TYPE_VC` (voice command) |
| Mode | `AFE_MODE_LOW_COST` |
| Noise suppression | NSNET2 |
| VAD | WebRTC (fallback via NULL model name) |
| AGC | Enabled, 9dB compression, -3 dBFS target, 3.0× gain |
| WakeNet | Disabled (weak stubs) |
| Models | Loaded from `model` partition (mmap) |

### Server Connection

| Setting | Value |
|---------|-------|
| Host | `192.168.68.190` |
| Port | `8444` |
| Endpoint | `POST /api/v1/upload` |
| Auth | `X-API-Key` header |
| Protocol | HTTPS (self-signed cert) |

### Serial Commands

| Command | Action |
|---------|--------|
| `rec` | Start 5-second test recording |
| `stop` | Stop current recording |
| `vad` | Toggle VAD mode on/off |
| `upload` | Upload all recordings on SD |
| `ls` | List files in `/lifelog/` |
| `mic` | Toggle mic on/off |

## Memory Layout

| Region | Address | Size | Content |
|--------|---------|------|---------|
| Bootloader | 0x0000 | ~12KB | ESP32-S3 bootloader |
| Partition table | 0x8000 | 4KB | Custom OTA partitions |
| NVS | 0x9000 | 20KB | WiFi config, boot counter |
| OTA data | 0xE000 | 8KB | Active app slot selector |
| app0 | 0x10000 | 3MB | Firmware (primary) |
| app1 | 0x310000 | 3MB | Firmware (OTA backup) |
| model | 0x610000 | 1.9MB | esp-sr models (nsnet2 + mn4q8_cn) |
| Free | 0x800000 | ~1.8MB | Available |

**Total flash used:** ~6.2MB of 8MB

## File Layout (SD Card)

```
/lifelog/
  rec_00000.opus
  rec_00001.opus
  rec_00002.opus
  ...
```

- Sequential zero-padded filenames
- Monotonically increasing `fileIndex` (RAM only — lost on reboot)
- Pre-opened: next file opened after voice ends to avoid ~150ms FAT32 create latency
- Deleted after successful upload

## Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| `tzapu/WiFiManager` | ^2.0.17 | Captive portal WiFi setup |
| `sh123/esp32_opus` | ^1.0.3 | Opus encoder |
| `pschatzmann/codec-ogg` | GitHub HEAD | OGG container mux |
| `espressif/esp-sr` | Commit `4f1b5607` | AFE (NSNET2 + VAD) |

Linked esp-sr precompiled libraries: `esp_audio_front_end`, `esp_audio_processor`, `dl_lib`, `vadnet`, `nsnet`, `c_speech_features`, `fst`, `hufzip`, `multinet`, `wakenet`

Weak stubs provided for: FFT symbols (`dl_rfft_*`), dotprod, WakeNet handle — these link against precompiled libs but never execute (AFE type VC + disabled wakenet).
