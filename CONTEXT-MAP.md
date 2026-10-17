# Context Map

This is a multi-context monorepo. Each context has its own `CONTEXT.md` describing its domain model, key concepts, and source layout.

| Context     | `CONTEXT.md` location       | Scope                                      |
| ----------- | -------------------------- | ------------------------------------------ |
| `backend`   | `server/CONTEXT.md`         | FastAPI orchestrator, transcription worker, speaker-id, diarization, whisper-asr |
| `dashboard` | `dashboard/CONTEXT.md`      | React SPA, API client, auth, components     |
| `firmware`  | `firmware-ota/CONTEXT.md`   | ESP32-S3 OTA firmware, audio capture       |
| `device-sim`| `device-sim/CONTEXT.md`      | Device simulator, integration tests         |

System-wide architectural decisions live in `docs/adr/`. Context-specific ADRs may also exist under `src/<context>/docs/adr/` within each context.
