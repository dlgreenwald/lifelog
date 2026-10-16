# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT-MAP.md`** at the repo root — points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** at the root — read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill creates them lazily when terms or decisions actually get resolved.

## File structure

Multi-context repo — four contexts:

```
/
├── CONTEXT-MAP.md                    ← points to per-context CONTEXT.md files
├── docs/
│   └── adr/                         ← system-wide architectural decisions
├── server/                          ← backend context
│   └── src/
├── transcription-worker/             ← backend context
├── speaker-id/                      ← backend context
├── diarization/                    ← backend context
├── whisper-asr/                    ← backend context
├── dashboard/                      ← dashboard context
│   └── src/
├── firmware-ota/                   ← firmware context
│   └── src/
├── device-sim/                     ← device-sim context
│   └── src/
└── CONTEXT-MAP.md
```

## Contexts

| Context    | Sub-packages                               |
| ---------- | ------------------------------------------ |
| `backend`  | `server/`, `transcription-worker/`, `speaker-id/`, `diarization/`, `whisper-asr/` |
| `dashboard`| `dashboard/`                               |
| `firmware` | `firmware-ota/`                            |
| `device-sim`| `device-sim/`                             |

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders) — but worth reopening because…_
