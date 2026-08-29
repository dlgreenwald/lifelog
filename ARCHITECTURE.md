# LifeLog Architecture

## Table of Contents

- [Overview](#overview)
- [System Architecture](#system-architecture)
  - [Complete Ecosystem Diagram](#complete-ecosystem-diagram)
  - [Data Flow: Upload Pipeline](#data-flow-upload-pipeline)
  - [Data Flow: Dashboard Access](#data-flow-dashboard-access)
  - [Data Flow: Speaker Labeling](#data-flow-speaker-labeling)
- [Services](#services)
  - [Firmware (Wearable Recorder)](#firmware-wearable-recorder)
    - [Hardware](#hardware)
    - [FreeRTOS Task Architecture](#freertos-task-architecture)
    - [Audio Pipeline](#audio-pipeline)
    - [Power Management](#power-management)
  - [Server Orchestrator](#server-orchestrator)
    - [Authentication](#authentication)
    - [Audio Encryption](#audio-encryption)
    - [Database Schema](#database-schema)
    - [API Endpoints](#api-endpoints)
  - [Speaker ID Service](#speaker-id-service)
    - [API Endpoints](#speaker-id-api-endpoints)
  - [Web Dashboard](#web-dashboard)
- [Infrastructure](#infrastructure)
  - [Docker Compose](#docker-compose)
  - [TLS Certificate Generation](#tls-certificate-generation)
  - [Environment Variables](#environment-variables)
- [Security Model](#security-model)

---

## Overview

LifeLog is a voice-activated life journal system composed of five components:

1. **Wearable Recorder** — XIAO ESP32-S3 Sense with built-in PDM microphone captures audio, processes it through esp-sr AFE (noise suppression + VAD), compresses it with Opus/OGG, and uploads in chunks when WiFi is available
2. **Server Orchestrator** — FastAPI service that receives audio chunks, groups them into utterances, and runs a background worker pipeline for transcription, speaker identification, and LLM summarization
3. **Transcription Worker** — Standalone WhisperX microservice that handles both transcription and speaker diarization in one step (runs on GPU, polls server for jobs)
4. **Speaker ID Service** — ECAPA-TDNN microservice that matches voice segments to known speakers
5. **Web Dashboard** — React SPA for browsing recordings, TODOs, decisions, and labeling unknown speakers

Audio is encrypted at rest with per-user Fernet keys. All inter-service communication uses HTTPS with mutual TLS. The orchestrator is the only service with database access.

---

## System Architecture

### Complete Ecosystem Diagram

```mermaid
graph TB
    subgraph Wearable["Wearable Recorder (ESP32-S3)"]
        MIC[PDM Mic] -->|I2S 16kHz| AFE[esp-sr AFE<br/>NS + VAD]
        AFE --> RING[Ring Buffer<br/>32 slots]
        RING --> OPUS[Opus/OGG Encoder<br/>~24kbps]
        OPUS --> SD[SD Card Queue]
        SD --> UPLOAD[Chunked HTTPS Upload]
        UPLOAD -->|POST /api/v1/upload| SERVER
    end

    subgraph Server["Server Orchestrator (FastAPI :8443)"]
        API[API Router] --> AUTH{Auth Type}
        AUTH -->|X-API-Key| UPLOAD_EP[Upload Endpoint<br/>Chunked]
        AUTH -->|Bearer OIDC| DASH_EP[Dashboard Endpoints]
        UPLOAD_EP --> QUEUE[(Utterance Queue)]
        WORKER[Background Worker<br/>Polls queue] --> QUEUE
    end

    subgraph Pipeline["Asynchronous Pipeline"]
        WORKER[Background Worker<br/>Upload/session orchestration] --> QUEUE
        WORKER -->|POST /internal/transcription/claim| TRANS[Transcription Worker<br/>WhisperX GPU]
        TRANS -->|complete/fail| WORKER
        WORKER -->|HTTPS| SPEAKER_SVC[Speaker ID Service]
        WORKER -->|OpenAI-compatible API| LLM[Local LLM Summarization]
        WORKER -->|Write| DB[(PostgreSQL)]
    end

    subgraph GPU["GPU Services"]
        TRANS -->|ASR + alignment + diarization| RESULT[Raw text + speaker labels]
        SPEAKER_SVC -->|ECAPA-TDNN| NAMED[Named Speakers]
    end

    subgraph Dashboard["Web Dashboard (React :3000)"]
        DASH_EP -->|Read| DB
        DASH_EP -->|Decrypt on-the-fly| AUDIO_FILES[(Encrypted Audio)]
        WEB[SPA] -->|OIDC Login| DASH_EP
    end

    subgraph Storage["Storage"]
        DB --> USERS[(users)]
        DB --> RECORDINGS[(recordings)]
        DB --> VOICEPRINTS[(voiceprints)]
        DB --> SESSIONS[(sessions)]
        AUDIO_FILES -->|/data/audio/*.enc| DISK[(Disk)]
    end

    style Server fill:#2c3e50,color:#fff
    style Wearable fill:#27ae60,color:#fff
    style GPU fill:#8e44ad,color:#fff
    style Dashboard fill:#2980b9,color:#fff
    style Storage fill:#7f8c8d,color:#fff
```

### Data Flow: Upload Pipeline

```mermaid
sequenceDiagram
    participant Device as Wearable
    participant Server as Orchestrator
    participant Worker as Background Worker
    participant Transcriber as Transcription Worker (GPU)
    participant SID as Speaker ID Svc
    participant LLM as Local LLM (Ollama/llama.cpp)
    participant DB as PostgreSQL

    Device->>Server: POST /api/v1/upload<br/>X-API-Key + chunk data
    Server->>Server: Validate user, encrypt chunk, store audio
    Server->>DB: INSERT utterance_queue
    Server-->>Device: 200 {status: "enqueued"}
    Worker->>DB: Claim pending utterance, assign session
    Worker->>DB: INSERT quick transcription job
    Transcriber->>Server: POST /internal/transcription/claim
    Transcriber->>Server: GET /internal/transcription/audio/{job_id}
    Transcriber->>Transcriber: Quick ASR-only transcription
    Transcriber->>Server: POST /internal/transcription/complete/{job_id}
    Worker->>DB: Apply quick transcript to session utterance
    Worker->>DB: End idle session and queue ten-minute full jobs
    Transcriber->>Server: Claim full job, fetch timestamped audio
    Transcriber->>Transcriber: Concatenate, transcribe, align, diarize
    Transcriber->>Server: POST stage and complete with speaker WAV segments
    Worker->>Worker: Encrypt speaker segments and auto-enroll raw labels
    Worker->>SID: POST /identify with audio + voiceprints
    Worker->>LLM: Chat completion with chronological transcript
    Worker->>DB: Save recording, todos/decisions, and daily summary
    Worker->>DB: Mark session processed

```

### Data Flow: Dashboard Access

```mermaid
sequenceDiagram
    participant Browser as Web Browser
    participant Dashboard as React SPA
    participant Server as Orchestrator
    participant DB as PostgreSQL

    Browser->>Dashboard: Navigate to localhost:3000
    Dashboard->>Dashboard: OIDC login flow
    Dashboard->>Server: GET /api/v1/dashboard/calendar/{year}/{month}<br/>Authorization: Bearer <oidc_token>
    Server->>Server: Validate OIDC JWT<br/>→ user lookup by sub
    Server->>DB: SELECT DATE(timestamp), COUNT(*)<br/>FROM recordings WHERE user_id = ?
    DB-->>Server: [{ date, count }]
    Server-->>Dashboard: { dates[{date, count}] }

    Dashboard->>User: Render calendar with dots<br/>on days with recordings

    User->>Dashboard: Click day 15
    Dashboard->>Server: GET /api/v1/dashboard/recordings/2024-01-15
    Server->>DB: SELECT * FROM recordings<br/>WHERE user_id = ? AND DATE(timestamp) = ?
    DB-->>Server: recordings[]
    Server-->>Dashboard: { recordings[] }

    User->>Dashboard: Click recording #42
    Dashboard->>Server: GET /api/v1/dashboard/recording/42
    Server->>DB: SELECT * FROM recordings<br/>WHERE id = 42 AND user_id = ?
    Server-->>Dashboard: { id, timestamp, summary, speakers, todos, ... }

    User->>Dashboard: Play audio
    Dashboard->>Server: GET /api/v1/dashboard/audio/<uuid>.enc
    Server->>Server: Decrypt audio with user's Fernet key
    Server-->>Dashboard: StreamResponse (audio/opus)
```

### Data Flow: Speaker Labeling

```mermaid
sequenceDiagram
    participant User as Dashboard User
    participant Dashboard as React SPA
    participant Server as Orchestrator
    participant SID as Speaker ID Svc
    participant DB as PostgreSQL

    User->>Dashboard: Navigate to /speakers
    Dashboard->>Server: GET /api/v1/dashboard/unknown-speakers
    Server->>DB: SELECT * FROM recordings<br/>WHERE speakers::text LIKE '%Unknown%'
    Server-->>Dashboard: { recordings[{id, speakers, audio_filename}] }

    User->>Dashboard: Click segment, type "Alice"
    User->>Dashboard: Click "Label & Re-identify"

    Dashboard->>Server: POST /api/v1/speakers/label<br/>Body: { recording_id: 5,<br/>speaker_id: "Unknown",<br/>label: "Alice" }

    par Label and enroll
        Server->>DB: UPDATE recordings SET speakers =<br/>jsonb_set(...)<br/>WHERE id = 5
    and
        Server->>Server: Decrypt audio from recording #5
        Server->>SID: POST /enroll?name=Alice<br/>File: <decrypted audio>
        SID->>SID: Extract ECAPA-TDNN embedding
        SID-->>Server: { name: "Alice",<br/>embedding: [0.1, 0.2, ...] }
        Server->>DB: INSERT INTO voiceprints<br/>(user_id, name, embedding)<br/>ON CONFLICT DO UPDATE
    end

    Server->>Server: rerun_identification(user):<br/>For each recording with Unknowns:<br/>decrypt → re-identify with new voiceprint

    Server->>DB: UPDATE recordings SET speakers = ...
    Server-->>Dashboard: { status: "labeled", label: "Alice" }
```

---

## Services

### Firmware (Wearable Recorder)

See **[firmware-ota/](firmware-ota/)** for source code, **[firmware-ota/ARCHITECTURE.md](firmware-ota/ARCHITECTURE.md)** for FreeRTOS task model and PlantUML diagrams.

#### Hardware

| Component | Part | Connection |
|-----------|------|------------|
| MCU | XIAO ESP32-S3 Sense | 8MB flash, 8MB PSRAM |
| Microphone | Built-in PDM mic | CLK=42, DIN=41 |
| SD Card | Built-in SPI slot | CS=21, MOSI=38, MISO=39, SCLK=40 |
| Battery | 400mAh LiPo | — |

#### FreeRTOS Task Architecture

| Task | Core | Priority | Stack | Purpose |
|------|------|----------|-------|---------|
| `afeFeedTask` | 0 | 5 | 8 KB | Reads I2S PDM mic, feeds esp-sr AFE |
| `afeFetchTask` | 1 | 5 | 8 KB | AFE fetch → VAD state machine → ring buffer |
| `writerTask` | 1 | 5 | 48 KB | Ring buffer → Opus encode → OGG mux → SD file |
| `uploadWorkerTask` | 1 | 1 | 8 KB | Background HTTP chunked uploads |
| Arduino `loop()` | 1 | 1 | default | OTA updates, stats logging |

**Core 0**: Only `afeFeedTask` — isolates I2S DMA from SD/WiFi contention.
**Core 1**: Everything else — audio processing, file I/O, network operations.

#### Audio Pipeline

```
PDM Mic (GPIO42/41)
  → I2S Driver (PDM, 16kHz, 16-bit mono, DMA: 4×1024)
  → esp-sr AFE (NSNET2 noise suppression + WebRTC VAD)
  → Ring buffer (32 slots × 512 samples = 32KB)
  → Opus encoder (24kbps, 20ms frames) → OGG mux
  → SD card (/lifelog/rec_*.opus)
  → HTTP POST multipart chunks → server
```

**VAD behavior**: Recording activates when WebRTC VAD detects speech. Pre-trigger cache (8192 samples) preserves audio before VAD onset. Short utterances (<4KB) are discarded without touching SD.

**Deferred SD open**: OGG pages buffer in PSRAM (16KB) before opening SD file, eliminating SD latency during voice onset.

**WiFi reconnect**: Exponential backoff (1s → 30s max). On reconnect, the SD queue is flushed FIFO.

---

### Server Orchestrator

FastAPI application on port 8443 (HTTPS). The **only** service with direct database access.

#### Authentication

Two authentication mechanisms:

| Method | Used By | Header | Validation |
|--------|---------|--------|------------|
| API Key | Wearable devices | `X-API-Key: <key>` | Lookup in `users.api_key` |
| OIDC JWT | Web dashboard | `Authorization: Bearer <token>` | Verify RS256 signature, audience, issuer; lookup by `sub` claim |

**Critical design rule**: The `X-API-Key` and OIDC `sub` are **not** the same identity space. A user can have an API key for device uploads and a separate OIDC subject for dashboard access. Both map to the same `users` row.

#### Audio Encryption

Audio files are encrypted with per-user Fernet symmetric keys:

```
Key derivation: PBKDF2-SHA256(password=user.encryption_secret, salt="lifelog-{user_id}", iterations=100000)
Storage: /data/audio/{uuid}.enc
```

- Each user gets a unique `encryption_secret` (64-char hex) generated at account creation
- The same secret + user ID always produces the same key (deterministic)
- Decryption requires both the correct user ID and secret — wrong user or wrong secret fails
- Audio is decrypted **on-the-fly** when streaming to the dashboard; never stored unencrypted on disk

#### Database Schema

```mermaid
erDiagram
    users {
        serial id PK
        text api_key UK "Device authentication"
        text oidc_sub UK "OIDC subject identifier"
        text name "Display name"
        text encryption_secret "Fernet key derivation secret"
        timestamp created_at
    }

    recordings {
        serial id PK
        integer user_id FK
        timestamp timestamp "When recorded"
        jsonb transcript "Raw Whisper output"
        jsonb speakers "Named segments with timing"
        text summary "LLM-generated summary"
        jsonb todos "Extracted action items"
        jsonb calendar "Extracted events"
        jsonb notes "Key points"
        jsonb conversation_changes "Topic transitions"
        text audio_filename "Encrypted file on disk"
        timestamp created_at
    }

    voiceprints {
        serial id PK
        integer user_id FK
        text name "Speaker label"
        bytea embedding "ECAPA-TDNN vector"
        timestamp created_at
    }

    users ||--o{ recordings : "has"
    users ||--o{ voiceprints : "has"
```

**Indexes**: `idx_recordings_user_timestamp` on `(user_id, timestamp)`, `idx_voiceprints_user` on `(user_id)`.

**Encryption at rest**: PostgreSQL runs with `ssl=on`. Connection pool uses `ssl='require'`. For production, add LUKS/dm-crypt on the host filesystem.

#### API Endpoints

All endpoints are prefixed with `/api/v1`.

##### `POST /api/v1/upload`

**Auth**: `X-API-Key` header (required)
**Content-Type**: `multipart/form-data`

Accepts Opus audio chunks from a wearable device. The device sends multiple chunks per utterance, with the final chunk marked `is_final=true`.

**Request fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `chunk` | file | yes | Opus audio chunk |
| `utterance_id` | int | yes | Device-assigned utterance ID |
| `chunk_index` | int | yes | Chunk sequence number (0-based) |
| `is_final` | bool | yes | True for the last chunk of an utterance |
| `session_id` | int | no | Optional session grouping ID |

**Behavior**:
- Each chunk is encrypted and stored on disk
- When `is_final=true`, the utterance is enqueued for background processing
- The background worker picks up pending utterances and runs the full pipeline

**Response** (chunk received):
```json
{ "status": "chunk_received", "utterance_id": 123 }
```

**Response** (utterance complete):
```json
{ "status": "processed", "utterance_id": 123 }
```

**Background pipeline** (executed asynchronously by separate workers):

| Step | Service | Protocol | Description |
|------|---------|----------|-------------|
| 1 | Orchestrator | — | Encrypt chunks, assign sessions, queue quick ASR jobs |
| 2 | Transcription worker | Internal HTTPS | Claim jobs, decode timestamped audio, run ASR/alignment/diarization |
| 3 | Orchestrator | — | Apply quick transcripts; persist encrypted full-job speaker segments |
| 4 | Speaker ID service | HTTPS | Match segment audio to user voiceprints |
| 5 | OpenAI-compatible API | HTTPS | Summarize chronological named segments |
| 6 | PostgreSQL | SSL | Store recording, todos/decisions, and daily summary |

**Non-obvious behavior**: quick jobs update active utterances as soon as ASR completes. Idle sessions are split into ten-minute full jobs, and finalization waits for every required job before persisting a recording. The server is the only DB-connected service; GPU workers receive audio and voiceprints in request bodies.

---

##### `GET /api/v1/utterance/{utterance_id}/status`

**Auth**: `X-API-Key` header (required)

Check processing status of an utterance.

**Response**:
```json
{
  "utterance_id": 123,
  "status": "processing",
  "recording_id": null
}
```

Status values: `pending`, `processing`, `done`, `failed`.

---

##### `GET /api/v1/dashboard/calendar/{year}/{month}`

**Auth**: OIDC Bearer token (required)
**Path params**: `year` (int), `month` (int, 1-12)

Returns days in the given month that have recordings, with counts.

**Response**:
```json
{
  "dates": [
    { "date": "2024-01-15", "count": 3 },
    { "date": "2024-01-20", "count": 1 }
  ]
}
```

**Non-obvious behavior**: This endpoint executes raw SQL directly (not through the database module) because it needs `GROUP BY` aggregation that the other query functions don't support.

---

##### `GET /api/v1/dashboard/recordings/{date}`

**Auth**: OIDC Bearer token (required)
**Path params**: `date` (string, format `YYYY-MM-DD`)

Returns all recordings for the authenticated user on the given date.

**Response**:
```json
{
  "recordings": [
    {
      "id": 1,
      "timestamp": "2024-01-15T10:30:00",
      "summary": "Morning standup discussion",
      "speakers": [...],
      "todos": [...]
    }
  ]
}
```

---

##### `GET /api/v1/dashboard/recording/{recording_id}`

**Auth**: OIDC Bearer token (required)
**Path params**: `recording_id` (int)

Returns full recording details. Returns 404 if not found or not owned by the user.

**Response**: Full recording row including `transcript`, `speakers`, `summary`, `todos`, `calendar`, `notes`, `conversation_changes`, `audio_filename`.

**Non-obvious behavior**: The `speakers` field contains the **merged** output — each entry has `id`, `name`, `start`, `end`, and `text` (the transcript text attributed to that speaker segment). Unknown speakers have `name: "Unknown"`.

---

##### `GET /api/v1/dashboard/audio/{filename}`

**Auth**: OIDC Bearer token (required)
**Path params**: `filename` (string, the `.enc` filename)

Streams the decrypted audio file. The file is decrypted using the authenticated user's encryption secret — **not** just by filename. Requesting another user's audio file will fail with a decryption error.

**Response**: `StreamingResponse` with `Content-Type: audio/opus`

**Non-obvious behavior**: This is the only endpoint that streams binary data. The audio is decrypted entirely in memory before streaming — there is no temp file on disk.

---

##### `GET /api/v1/dashboard/todos`

**Auth**: OIDC Bearer token (required)

Aggregates all TODOs across all recordings for the user. Each todo includes `recording_id` and `recording_timestamp` for provenance.

**Response**:
```json
{
  "todos": [
    {
      "task": "Write proposal",
      "owner": "Alice",
      "due": "2024-01-20",
      "priority": "high",
      "recording_id": 5,
      "recording_timestamp": "2024-01-15T10:00:00"
    }
  ]
}
```

---

##### `GET /api/v1/dashboard/decisions`

**Auth**: OIDC Bearer token (required)
**Query params**: `limit` (int, optional, default: 20)

Returns recent recordings that contain decisions.

**Response**:
```json
{
  "decisions": [
    {
      "id": 1,
      "timestamp": "2024-01-15T10:00:00",
      "summary": "Decided to launch v2 on Friday"
    }
  ]
}
```

**Non-obvious behavior**: This endpoint returns **recording summaries** (not extracted decision objects). The dashboard displays the summary text which contains the decisions. The actual decision objects are inside each recording's `todos`/`speakers` JSONB.

---

##### `GET /api/v1/dashboard/unknown-speakers`

**Auth**: OIDC Bearer token (required)

Returns all recordings where the `speakers` JSONB contains `"Unknown"`. Used by the speaker labeling UI.

**Response**:
```json
{
  "recordings": [
    {
      "id": 5,
      "timestamp": "2024-01-15T10:00:00",
      "speakers": [{"name": "Unknown", "start": 0, "end": 2.5, "text": "..."}],
      "audio_filename": "abc123.enc"
    }
  ]
}
```

**Non-obvious behavior**: The query uses `speakers::text LIKE '%Unknown%'` — a text-level search on the JSONB column. This matches any segment with "Unknown" in any field, not just the `name` field. In practice this is fine because "Unknown" only appears as a speaker name.

---

##### `POST /api/v1/speakers/label`

**Auth**: OIDC Bearer token (required)
**Content-Type**: `application/json`

Labels an unknown speaker and triggers re-identification across all recordings.

**Request body**:
```json
{
  "recording_id": 5,
  "speaker_id": "Unknown",
  "label": "Alice"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `recording_id` | int | yes | ID of the recording containing the unknown speaker |
| `speaker_id` | string | yes | The speaker identifier to replace (typically `"Unknown"`) |
| `label` | string | yes | The name to assign to this speaker |

**Response**:
```json
{ "status": "labeled", "label": "Alice" }
```

**Non-obvious behavior**: This endpoint does 4 things in sequence:

1. Updates the speaker name in the recording's `speakers` JSONB
2. Sends the recording's audio to the speaker-id service's `/enroll` endpoint to extract an ECAPA-TDNN embedding
3. Saves the embedding as a voiceprint in the database (upserts on `(user_id, name)` conflict)
4. Runs `rerun_identification()` which iterates **every** recording with unknown speakers, decrypts each audio file, re-runs speaker identification with the new voiceprint, and updates the recording

This means labeling one speaker can retroactively identify that speaker in all past recordings.

---

### Whisper ASR Service

Docker container running WhisperX for both transcription and speaker diarization. No database access.

**GPU required**. Runs on CUDA by default. Uses `whisperx` which combines Whisper transcription with pyannote.audio diarization in a single step.

```mermaid
graph LR
    AUDIO[Audio Bytes] --> WHISPERX[WhisperX<br/>large-v3 + pyannote]
    WHISPERX --> RESULT[Transcription<br/>+ Diarization]
```

#### Whisper ASR API Endpoints

##### `POST /transcribe`

**Content-Type**: `multipart/form-data` or raw bytes

Performs transcription and diarization on uploaded audio.

**Request**: `file` — audio file (Opus format)

**Response**:
```json
{
  "text": "Hello, how are you?",
  "segments": [
    { "speaker": "SPEAKER_00", "start": 0.0, "end": 2.5, "text": "Hello" },
    { "speaker": "SPEAKER_01", "start": 2.5, "end": 5.0, "text": "How are you?" }
  ]
}
```

**Non-obvious behavior**: Unlike the old separate diarization service, WhisperX handles both transcription and diarization in one step. Speaker labels are opaque IDs (`SPEAKER_00`, etc.) — they are not meaningful names. The orchestrator uses the `start`/`end` timestamps to correlate with speaker identification results. The service auto-unloads models after 300s of idle time to free GPU memory.

---

##### `GET /health`

**Response**:
```json
{ "status": "healthy" }
```

---

### Speaker ID Service

Standalone FastAPI microservice. Uses SpeechBrain's ECAPA-TDNN for speaker embeddings. No database access.

**GPU required**. Runs on CUDA by default.

```mermaid
graph LR
    AUDIO[Audio Segment] --> EMBED[ECAPA-TDNN<br/>speechbrain/spkrec-ecapa-voxceleb]
    EMBED --> VECTOR[192-dim Embedding]
    VECTOR --> MATCH{Cosine Similarity<br/>> 0.75?}
    MATCH -->|Yes| NAME[Return Speaker Name]
    MATCH -->|No| UNKNOWN["Return 'Unknown'"]
```

#### Speaker ID API Endpoints

##### `POST /identify`

**Content-Type**: `application/json`

Identifies speakers in diarized segments using provided voiceprints.

**Request body**:
```json
{
  "segments": [
    { "speaker": "SPEAKER_00", "start": 0.0, "end": 2.5 }
  ],
  "voiceprints": [
    { "name": "Alice", "embedding": [0.1, 0.2, ...] }
  ],
  "audio_format": "opus"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `segments` | array | yes | Diarized segments with `speaker`, `start`, `end` |
| `voiceprints` | array | no | Known speaker embeddings (fetched by orchestrator from DB) |
| `audio_format` | string | no | Audio format hint (default: `"opus"`) |

**Response**:
```json
{
  "speakers": [
    { "speaker": "SPEAKER_00", "start": 0.0, "end": 2.5, "name": "Alice" },
    { "speaker": "SPEAKER_01", "start": 2.5, "end": 5.0, "name": "Unknown" }
  ]
}
```

**Non-obvious behavior**: Voiceprints are **passed in via the request**, not fetched from a database. The orchestrator queries its own database for the user's voiceprints and sends them to this service. This keeps the speaker-id service stateless and database-free. The `name` field defaults to `"Unknown"` when no voiceprint matches above the similarity threshold (0.75).

---

##### `POST /enroll`

**Query params**: `name` (string, required)
**Content-Type**: `multipart/form-data`

Extracts an ECAPA-TDNN embedding from an audio sample for enrollment.

**Request**: `file` — audio file (Opus, converted to WAV internally)

**Response**:
```json
{
  "name": "Alice",
  "embedding": [0.1, 0.2, 0.3, ...]
}
```

**Non-obvious behavior**: This endpoint returns the embedding to the **orchestrator** (not to the user). The orchestrator then saves it to the database via `save_voiceprint()`. The speaker-id service itself never persists data. The response embedding is a 192-dimensional float array.

---

##### Utility Functions (not endpoints)

| Function | Description |
|----------|-------------|
| `cosine_similarity(a, b)` | Computes cosine similarity between two numpy arrays |
| `match_voiceprint(embedding, voiceprints, threshold)` | Finds best matching voiceprint above threshold (default 0.75). Returns name or `"Unknown"` |
| `opus_to_wav(opus_bytes)` | Converts Opus to 16kHz mono WAV via ffmpeg subprocess. Cleans up temp files in `finally` block |

---

### Web Dashboard

React + TypeScript SPA served as static files. Built with Vite.

**Authentication**: OIDC login via `oidc-client-ts`. The SPA stores the access token and attaches it as `Authorization: Bearer <token>` to all API requests.

**Routes**:

| Path | Component | Description |
|------|-----------|-------------|
| `/` | `Calendar` | Monthly calendar with recording indicators; click day to see recordings |
| `/recording/:id` | `RecordingDetail` | Full recording view: summary, speakers, audio player, TODOs, decisions |
| `/todos` | `TodoList` | Aggregated TODOs across all recordings, with priority badges |
| `/decisions` | `DecisionsList` | Recent decisions from all recordings |
| `/speakers` | `SpeakerLabel` | Label unknown speakers; triggers re-identification |

**Audio playback**: The `AudioPlayer` component renders a timeline with colored segments per speaker. Clicking a segment seeks to that time. Unknown speakers are highlighted in red.

**No direct database access**: The dashboard talks only to the orchestrator's REST API.

---

## Infrastructure

### Docker Compose

```mermaid
graph TB
    subgraph Docker["docker-compose up -d"]
        PG[postgres:16-alpine<br/>:5432<br/>SSL on]
        SRV[server<br/>:8444→8443<br/>HTTPS]
        TRANS[transcription-worker<br/>:9001→9000<br/>GPU]
        SPK[speaker-id<br/>:8445→8443<br/>GPU]
        DASH[dashboard<br/>:3000→80<br/>nginx]
    end

    SRV --> PG
    SRV --> TRANS
    SRV --> SPK
    DASH --> SRV

    style PG fill:#336791,color:#fff
    style SRV fill:#2c3e50,color:#fff
    style TRANS fill:#e74c3c,color:#fff
    style SPK fill:#8e44ad,color:#fff
    style DASH fill:#2980b9,color:#fff
```

| Service | External Port | Internal Port | GPU | Dependencies |
|---------|--------------|---------------|-----|--------------|
| postgres | 5432 | 5432 | No | — |
| server | 8444 | 8443 | No | postgres (healthy), speaker-id |
| transcription-worker | 9001 | 9000 | Yes | server (healthy) |
| speaker-id | 8445 | 8443 | Yes | — |
| dashboard | 3000 | 80 | No | server |

### TLS Certificate Generation

Run `./scripts/generate-certs.sh` to create:

1. A self-signed CA certificate (`ca.key`, `ca.crt`)
2. Per-service server certificates signed by the CA:
   - `server/certs/server.{key,crt}`
   - `speaker-id/certs/server.{key,crt}`

Each service mounts its certs as read-only. The server also mounts the CA cert to verify speaker-id service identity.

### Environment Variables

| Variable | Required | Used By | Description |
|----------|----------|---------|-------------|
| `POSTGRES_PASSWORD` | Yes | server, postgres | Database password |
| `OPENAI_BASE_URL` | Yes | server | Local LLM endpoint (Ollama, llama.cpp, etc.) |
| `OPENAI_API_KEY` | No (default: ollama) | server | LLM API key |
| `OPENAI_MODEL` | No (default: qwen2.5:7b) | server | LLM model name |
| `HF_TOKEN` | Yes | transcription-worker | Hugging Face token for pyannote models |
| `OIDC_ISSUER_URL` | Yes | server | OIDC provider issuer URL |
| `OIDC_CLIENT_ID` | Yes | server | OIDC client ID |
| `OIDC_CLIENT_SECRET` | Yes | server | OIDC client secret |
| `OIDC_REDIRECT_URI` | Yes | server | OIDC redirect URI |
| `SPEAKER_ID_URL` | No (default: http://speaker-id:8443) | server | Speaker ID service URL |
| `AUDIO_STORAGE_PATH` | No (default: /data/audio) | server | Encrypted audio file storage |
| `POSTGRES_HOST` | No (default: localhost) | server | Database host |
| `POSTGRES_PORT` | No (default: 5432) | server | Database port |
| `POSTGRES_DB` | No (default: lifelog) | server | Database name |
| `POSTGRES_USER` | No (default: lifelog) | server | Database user |
| `LOG_LEVEL` | No (default: INFO) | server | Python log level |
| `CORS_ORIGINS` | No (default: http://localhost:3000) | server | Allowed CORS origins |

---

## Security Model

```mermaid
graph TB
    subgraph Trust["Trust Boundaries"]
        DEVICE["Device<br/>(X-API-Key)"]
        HTTPS_DEVICE["HTTPS + API Key"]
        SERVER["Orchestrator<br/>(owns DB + audio)"]
        HTTPS_SVC["HTTPS + mTLS"]
        GPU_SVC["GPU Services<br/>(stateless, no DB)"]
        HTTPS_DASH["HTTPS + OIDC"]
        DASH["Dashboard<br/>(browser)"]
    end

    DEVICE -->|X-API-Key header| HTTPS_DEVICE
    HTTPS_DEVICE -->|encrypt + store| SERVER
    SERVER -->|voiceprints in request body| HTTPS_SVC
    HTTPS_SVC -->|embeddings only| GPU_SVC
    DASH -->|OIDC Bearer token| HTTPS_DASH
    HTTPS_DASH -->|read-only queries| SERVER

    SERVER -.->|SSL required| DB[(PostgreSQL)]

    style SERVER fill:#2c3e50,color:#fff
    style GPU_SVC fill:#8e44ad,color:#fff
    style DB fill:#336791,color:#fff
```

**Key security properties**:

1. **Audio encryption at rest**: Every audio file is encrypted with a per-user Fernet key derived from PBKDF2. Even if disk is compromised, audio is unreadable without the user's secret.

2. **Database isolation**: Only the orchestrator connects to PostgreSQL. GPU services never see the database — voiceprints are passed in HTTP request bodies.

3. **HTTPS everywhere**: All inter-service communication uses TLS. Self-signed certs for development; Let's Encrypt for production.

4. **Per-user data isolation**: All database queries filter by `user_id`. The recording endpoint additionally checks ownership (`WHERE id = ? AND user_id = ?`).

5. **API key ≠ OIDC identity**: Device uploads (API key) and dashboard access (OIDC) are independent auth mechanisms that map to the same user record. A compromised API key cannot access the dashboard, and vice versa.

6. **GPU services are stateless**: the transcription-worker and speaker-id services hold no persistent state. They receive audio + voiceprints, return results, and forget. Compromising them exposes neither the database nor stored audio.

---

## Roadmap

### OAuth Device Flow (partial)

RFC 8628 OAuth Device Authorization Grant is implemented on the ESP32 side. Three key constraints:

1. **Device authorization flow**: device credentials are obtained through OAuth device authorization rather than being embedded in the firmware.

2. **Flash storage for tokens**: Refresh tokens are stored in ESP32 flash memory (persists across restarts and power failures), not on the SD card. SD cards are removable and less secure; flash is soldered to the board.

3. **Minimal scope**: Tokens are granted the narrowest scope required for their role. A compromised token cannot access endpoints outside its scope.

**Current state**: ESP32-side implementation complete (firmware-ota/lib/oauth2_device_flow/). The ESP32 uses OAuth2 device code flow to obtain JWT access tokens from the OIDC provider, which are then sent as Bearer tokens on upload requests. The server validates these JWTs via the OIDC provider's JWKS.

**Note on TTS**: The roadmap originally included TTS playback for the user authorization code. This is not applicable to the XIAO ESP32-S3 Sense board, which has no audio output. Device authorization requires an external screen or SSH tunnel for the user to enter the code manually. The token storage and refresh logic is fully implemented regardless.

**Token scope enforcement** (write:recordings, read:recordings, etc.) at the server level is not yet implemented — this is a v2 item.
