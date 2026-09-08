"""Device simulator — replays a meeting through the lifelog upload API in real time."""

from __future__ import annotations

import os
import random
import time
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from pathlib import Path

import httpx

from device_sim.auth import DeviceAuthenticator
from device_sim.encode import encode_opus, encode_silent_opus
from device_sim.slicer import UtteranceSlice, slice_meeting


class UploadMode(Enum):
    """Controls upload order and timestamp behavior.

    - NORMAL: upload in recording order with current timestamps (device just finished).
    - OUT_OF_ORDER: upload shuffled but timestamps reflect true recording time.
    - DELAYED: upload with timestamps 7 days in the past (offline recording session).
    """

    NORMAL = auto()
    OUT_OF_ORDER = auto()
    DELAYED = auto()


class Simulator:
    """Replays meeting utterances through the lifelog upload API.

    Args:
        server_url: base URL of the lifelog server (e.g. http://localhost:8443).
        meeting_id: AMI meeting ID to simulate.
        authenticator: TestAuthenticator instance for OIDC tokens.
        device_start_ahead_seconds: how many seconds before the meeting start the
            device "was turned on" (used to set realistic device timestamps).
        upload_interval_seconds: pause between uploads (slightly > chunk so chunks
            don't overlap in time).
        mode: controls upload order and timestamp behavior (see UploadMode).
    """

    def __init__(
        self,
        server_url: str,
        meeting_id: str,
        authenticator: DeviceAuthenticator,
        device_start_ahead_seconds: float = 120.0,
        upload_interval_seconds: float = 5.1,
        mode: UploadMode = UploadMode.NORMAL,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.meeting_id = meeting_id
        self.auth = authenticator
        self.device_start_ahead = device_start_ahead_seconds
        self.upload_interval = upload_interval_seconds
        self.mode = mode

        self.device_start_time: datetime | None = None
        self.device_utterance_id = 0
        self.chunk_index = 0
        self.utterances: list[UtteranceSlice] = []
        self.uploaded_server_ids: list[int] = []

    def prepare(self, ami_data_dir: str) -> list[UtteranceSlice]:
        """Slice the meeting audio and pre-encode all utterances to Opus.

        Args:
            ami_data_dir: path to device-sim/data/{meeting_id}/.

        Returns:
            list of UtteranceSlice in replay order.
        """
        data_dir = Path(ami_data_dir)
        wav_path = str(data_dir / f"{self.meeting_id}.headset.wav")
        annotation_zip = str(data_dir / "annotations.zip")
        output_dir = str(data_dir / "utterances")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        max_utterances = int(os.environ.get("MAX_UTTERANCES", "0"))

        self.utterances = slice_meeting(
            wav_path=wav_path,
            annotation_zip_path=annotation_zip,
            output_dir=output_dir,
            max_utterances=max_utterances,
            meeting_id=self.meeting_id,
        )

        for utt in self.utterances:
            opus_path = utt.wav_path.replace(".wav", ".opus")
            if utt.is_silence:
                encode_silent_opus(utt.end_s - utt.start_s, opus_path)
            else:
                encode_opus(utt.wav_path, opus_path)
            # Mutate in-place so upload_all can find the opus path
            object.__setattr__(utt, "opus_path", opus_path)

        return self.utterances

    def _upload_one(
        self, utt: UtteranceSlice, recorded_at: int | None = None
    ) -> int | None:
        """Upload a single utterance with retries for transient errors."""
        if not Path(utt.opus_path).exists():
            raise FileNotFoundError(f"Opus file not found: {utt.opus_path}")

        with Path(utt.opus_path).open("rb") as f:
            audio_bytes = f.read()

        filename = f"rec_{self.device_utterance_id:05d}.opus"

        # Build request data; recorded_at is the device's UTC epoch timestamp
        data = {
            "utterance_id": str(self.device_utterance_id),
            "chunk_index": "0",
            "is_final": "true",
        }
        if recorded_at is not None:
            data["recorded_at"] = str(recorded_at)

        # Retry transient errors (timeout, connect) with backoff
        for attempt in range(3):
            token = self.auth.get_token()
            headers = {"Authorization": f"Bearer {token}"}
            with httpx.Client(timeout=60.0) as client:
                try:
                    resp = client.post(
                        f"{self.server_url}/api/v1/upload",
                        headers=headers,
                        files={
                            "file": (filename, audio_bytes, "application/octet-stream"),
                        },
                        data=data,
                    )
                except (
                    httpx.ReadTimeout,
                    httpx.ConnectError,
                    httpx.NetworkError,
                ) as exc:
                    if attempt < 2:
                        time.sleep(2**attempt)
                        continue
                    raise RuntimeError(
                        f"Upload request failed after 3 attempts: {exc}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise RuntimeError(f"Upload request failed: {exc}") from exc

                if resp.status_code == 401:
                    self.auth.refresh()
                    token = self.auth.get_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    resp = client.post(
                        f"{self.server_url}/api/v1/upload",
                        headers=headers,
                        files={
                            "file": (filename, audio_bytes, "application/octet-stream"),
                        },
                        data=data,
                    )

                if resp.status_code not in (200, 201):
                    raise RuntimeError(
                        f"Upload failed with {resp.status_code}: {resp.text}",
                    )

                payload = resp.json()
                return payload.get("server_utt_id") or payload.get("utterance_id")

        return None

    def upload_all(self) -> list[int]:
        """Upload all prepared utterances.

        In NORMAL mode: uploads in recording order with current timestamps (device
        just finished recording). In OUT_OF_ORDER mode: shuffles upload order but
        uses true recording timestamps so server orders correctly by recorded_at.
        In DELAYED mode: timestamps are 7 days in the past, simulating an offline
        recording session that syncs much later.

        Returns:
            list of server-assigned utterance IDs.
        """
        if not self.utterances:
            raise RuntimeError("No utterances prepared. Call prepare() first.")

        # DELAYED mode: device_start_ahead of 7 days so recorded_at is ~7 days ago.
        # This exercises the server's ±7-day timestamp validation.
        device_start_ahead = self.device_start_ahead
        if self.mode == UploadMode.DELAYED:
            device_start_ahead = 7 * 24 * 3600

        self.device_start_time = datetime.now(UTC) - timedelta(
            seconds=device_start_ahead
        )
        self.uploaded_server_ids = []

        # OUT_OF_ORDER mode: shuffle upload order but compute recorded_at from
        # original start_s so the server sees true recording timestamps.
        upload_order = self.utterances[:]
        if self.mode == UploadMode.OUT_OF_ORDER:
            random.shuffle(upload_order)

        for utt in upload_order:
            # recorded_at = device boot + audio start offset (Unix epoch seconds)
            target_time = self.device_start_time + timedelta(seconds=utt.start_s)
            recorded_at = int(target_time.timestamp())

            # Only sleep for NORMAL mode — out-of-order/delayed skip timing simulation
            if self.mode == UploadMode.NORMAL:
                now = datetime.now(UTC)
                wait_s = (target_time - now).total_seconds()
                if wait_s > 0:
                    time.sleep(wait_s)

            server_id = self._upload_one(utt, recorded_at=recorded_at)
            if server_id is not None:
                self.uploaded_server_ids.append(int(server_id))

            self.device_utterance_id += 1
            self.chunk_index = 0

            # Sleep between uploads (skip on last); only in NORMAL mode
            if self.mode == UploadMode.NORMAL and utt != upload_order[-1]:
                time.sleep(self.upload_interval)

        return self.uploaded_server_ids

    def poll_until_done(
        self,
        timeout_s: float = 900.0,
    ) -> dict[int, str]:
        """Poll utterance status until all are completed/failed or timeout.

        Returns:
            dict mapping server_id -> status string.
        """
        deadline = time.monotonic() + timeout_s
        token = self.auth.get_token()
        headers = {"Authorization": f"Bearer {token}"}

        result: dict[int, str] = {}

        while time.monotonic() < deadline:
            if not self.uploaded_server_ids:
                break

            done = True
            for sid in self.uploaded_server_ids:
                status = result.get(sid, "unknown")
                if status in ("completed", "failed"):
                    continue

                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(
                        f"{self.server_url}/api/v1/utterance/{sid}/status",
                        headers=headers,
                    )
                    if resp.status_code == 200:
                        result[sid] = resp.json().get("status", "unknown")
                    elif resp.status_code == 404:
                        result[sid] = "not_found"
                    else:
                        result[sid] = f"error_{resp.status_code}"

                if result[sid] not in ("completed", "failed"):
                    done = False

            if done:
                break

            time.sleep(5.0)

        return result
