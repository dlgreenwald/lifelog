# Device Simulator

Replays real multi-party meeting audio through the same API surface the ESP32 firmware uses. Uses the AMI Meeting Corpus as the audio source, encoding to Opus and uploading via the lifelog upload API. Serves as the foundation for integration tests where inputs are deterministic and outputs are verifiable.

## Prerequisites

- **ffmpeg** with libopus support:

  ```bash
  # Ubuntu/Debian
  sudo apt install ffmpeg

  # macOS
  brew install ffmpeg
  ```

- **lifelog stack running** (`docker-compose up -d` from repo root). The simulator hits `DEVICE_SIM_SERVER_URL` directly — no stack services are required by the simulator itself.

## Goauthentik Setup

The simulator uses the Resource Owner Password Credentials grant — no browser, no redirect URI. Create a dedicated OAuth application:

1. Goauthentik → **Applications** → **Create**
2. **Name**: `lifelog-simulator`
3. **Client Type**: `Confidential`
4. **Grant Types**: check **Resource Owner Password Credentials**
5. **Redirect URI**: `http://localhost` (required by Goauthentik even for password grant)
6. Save — copy the **Client ID** and **Client Secret**

Also ensure the test user (`testUser`) has **OpenID Connect** enabled under **Sources** in their user settings.

## Configuration

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `DEVICE_SIM_OIDC_ISSUER` | OIDC provider discovery URL (same as server uses) |
| `DEVICE_SIM_CLIENT_ID` | OAuth app client ID from Goauthentik |
| `DEVICE_SIM_CLIENT_SECRET` | OAuth app client secret from Goauthentik |
| `DEVICE_SIM_USERNAME` | Test user username in Goauthentik |
| `DEVICE_SIM_PASSWORD` | Test user password |
| `DEVICE_SIM_TEST_OIDC_SUB` | The OIDC `sub` claim for the test user (deterministic hash, not the username). Run once with the real user and decode the JWT's `sub` claim to find it. |
| `DEVICE_SIM_SERVER_URL` | Lifelog server URL (default: `http://localhost:8444`) |
| `MEETING_ID` | AMI meeting ID to replay (default: `EN2001a`) |
| `MAX_UTTERANCES` | Cap utterances per run; `0` = no limit (default: `0`) |
| `SILENCE_INSERT_EVERY` | Insert a silence artifact every N real utterances; `0` = disabled (default: `0`) |
| `SILENCE_INSERT_PROBABILITY` | Probability of inserting silence (default: `0.5`) |

**Finding `DEVICE_SIM_TEST_OIDC_SUB`:** decode any acquired JWT's payload:

```python
import base64, json, jwt
payload = jwt.decode(token, options={"verify_signature": False})
print(payload["sub"])  # paste this as DEVICE_SIM_TEST_OIDC_SUB
```

## Downloading AMI Data

One-time setup (downloads ~200 MB):

```bash
cd device-sim
uv venv .venv
uv pip install -e ".[dev]"
.venv/bin/python -m device_sim.scripts.download_ami
```

Data lands in `data/{MEETING_ID}/`:
- `{MEETING_ID}.headset.wav` — mono headset mix
- `annotations.zip` — NITE XML with word-level timestamps and speaker segments
- `{MEETING_ID}.info.xml` — participant ID mapping

## Running the Simulator Manually

```bash
.venv/bin/python -c "
from device_sim.auth import DeviceAuthenticator
from device_sim.simulator import Simulator
import os
from pathlib import Path

# Load env
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k] = v

auth = DeviceAuthenticator()
sim = Simulator(
    server_url=os.environ['DEVICE_SIM_SERVER_URL'],
    meeting_id=os.environ['MEETING_ID'],
    authenticator=auth,
)

# Override max utterances for quick run
import os
os.environ['MAX_UTTERANCES'] = '5'

sim.prepare(f'data/{os.environ[\"MEETING_ID\"]}')
ids = sim.upload_all()
print(f'Uploaded {len(ids)} utterances: {ids}')
"
```

## Running Tests

```bash
# Load .env and run
.venv/bin/python -c "
import os
from pathlib import Path
for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        os.environ[k] = v
import subprocess, sys
sys.exit(subprocess.run(['.venv/bin/python', '-m', 'pytest', 'tests/', '-v'], env=os.environ.copy()).returncode)
"
```

Tests take ~3–4 minutes. Each test uploads 5–15 utterances and exercises:

| Test | What it verifies |
|---|---|
| `test_auth_token_acquired` | `DeviceAuthenticator` fetches and caches a valid JWT |
| `test_slice_and_encode_small` | 5 utterances sliced and encoded correctly |
| `test_truncated_meeting_upload` | 15-utterance upload returns valid server IDs |
| `test_silence_artifact_handling` | Silence artifacts encode and upload without error |
| `test_device_reboot_all_utterances_same_session` | All utterances in one session |
| `test_auth_refresh_on_401` | Upload succeeds after one 401→retry round-trip |

The transcription pipeline is **not** waited for in tests (`poll_until_done` skipped — takes 10–15 min for the full meeting). Full pipeline verification is done in `e2e/run_e2e.py`.

## Architecture

```
device-sim/
├── src/device_sim/
│   ├── auth.py          # DeviceAuthenticator: password-grant OIDC token fetch + cache
│   ├── slicer.py        # AMI NITE XML parser; builds UtteranceSlice list
│   ├── encode.py        # ffmpeg → Opus encoding (real + silence)
│   ├── simulator.py      # Simulator: real-time replay orchestration
│   └── scripts/
│       └── download_ami.py  # AMI corpus download + annotation extraction
└── tests/
    ├── conftest.py      # Fixtures: ami_data_dir, test_oidc_sub
    └── test_simulator.py # Integration tests
```

**Upload flow:**

```
Simulator.prepare()
  └─ slice_meeting()       → parse NITE XML → list[UtteranceSlice]
  └─ encode_opus()          → ffmpeg WAV → Opus

Simulator.upload_all()
  └─ POST /api/v1/upload   → multipart: file + utterance_id + chunk_index + is_final
  └─ on 401 → auth.refresh() → retry once

Simulator.poll_until_done()   (not called in fast tests)
  └─ GET /api/v1/utterance/{id}/status → wait for "completed"
```

**Server-side auth:** the server accepts tokens from both the main Goauthentik app (`OIDC_CLIENT_ID`) and the simulator app (`OIDC_SIMULATOR_CLIENT_ID`). The token's `iss` claim is derived from the JWT itself, so multi-issuer support works automatically.
