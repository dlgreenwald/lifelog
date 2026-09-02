"""End-to-end pipeline integration tests.

These tests upload utterances via the device simulator, wait for the
transcription pipeline to complete, and verify the resulting transcripts.

Requires a live server stack (docker-compose up) with transcription-worker
and speaker-id services. Tests are skipped if the server is unreachable.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
import pytest

from device_sim.auth import DeviceAuthenticator
from device_sim.simulator import Simulator


def _server_reachable(url: str) -> bool:
    """Check if the server is reachable."""
    try:
        resp = httpx.get(f"{url}/health", timeout=5)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.ReadTimeout, httpx.NetworkError):
        return False


def _poll_until_status(
    server_url: str,
    token: str,
    utterance_ids: list[int],
    timeout_s: float = 300.0,
    poll_interval_s: float = 5.0,
) -> dict[int, str]:
    """Poll utterance status until all are done/failed or timeout.

    Returns dict of utterance_id -> final status.
    """
    start = time.monotonic()
    pending = set(utterance_ids)
    status: dict[int, str] = {}

    while pending:
        if time.monotonic() - start > timeout_s:
            raise TimeoutError(
                f"Timed out after {timeout_s}s waiting for utterances: {pending}"
            )
        for uid in list(pending):
            resp = httpx.get(
                f"{server_url}/api/v1/utterance/{uid}/status",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                s = data.get("status", "unknown")
                if s in ("done", "failed", "unknown"):
                    status[uid] = s
                    pending.discard(uid)
        if pending:
            time.sleep(poll_interval_s)

    return status


def _get_recording_transcript(
    server_url: str, token: str, session_id: int
) -> list[dict[str, Any]]:
    """Fetch the most recent recording for a session and return its transcript segments."""
    # Get latest recording for this user
    resp = httpx.get(
        f"{server_url}/api/v1/dashboard/recordings",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    recordings = resp.json()
    # Find recording for this session
    for rec in recordings:
        if rec.get("session_id") == session_id:
            # Fetch full recording detail
            detail_resp = httpx.get(
                f"{server_url}/api/v1/dashboard/recording/{rec['id']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if detail_resp.status_code == 200:
                return detail_resp.json().get("transcript", {}).get("segments", [])
    return []


class TestPipeline:
    """End-to-end pipeline tests: upload → transcribe → verify transcript."""

    @pytest.mark.integration
    def test_upload_5_utterances_transcribed(self, ami_data_dir: str) -> None:
        """Upload 5 utterances; verify transcription completes and transcript is non-empty."""
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable — start with docker-compose up")

        os.environ["MAX_UTTERANCES"] = "5"
        try:
            auth = DeviceAuthenticator()
            sim = Simulator(
                server_url=os.environ["DEVICE_SIM_SERVER_URL"],
                meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
                authenticator=auth,
            )
            sim.prepare(ami_data_dir)
            assert len(sim.utterances) == 5, f"Expected 5 utterances, got {len(sim.utterances)}"

            ids = sim.upload_all()
            assert len(ids) == 5, f"Expected 5 server IDs, got {len(ids)}"

            # Poll until all utterances are done (or failed)
            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=300.0,
            )

            # All should be done (not failed)
            assert all(s == "done" for s in status_map.values()), (
                f"Some utterances did not complete successfully: {status_map}"
            )

            # Verify transcripts are non-empty via dashboard API
            # Get the session_id from the most recent session for this user
            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert resp.status_code == 200, f"Failed to fetch recordings: {resp.text}"

            # At least one recording should exist now
            recordings = resp.json()
            assert len(recordings) > 0, "Expected at least one recording after transcription"

            # Verify the most recent recording has a non-empty transcript
            latest = recordings[-1]
            detail_resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{latest['id']}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert detail_resp.status_code == 200
            recording = detail_resp.json()
            segments = recording.get("transcript", {}).get("segments", [])
            assert len(segments) > 0, (
                f"Expected non-empty transcript segments, got: {segments}"
            )

            # Each segment should have text and a speaker
            for seg in segments:
                assert seg.get("text"), f"Segment missing text: {seg}"
                assert seg.get("speaker"), f"Segment missing speaker: {seg}"

        finally:
            os.environ.pop("MAX_UTTERANCES", None)

    @pytest.mark.integration
    def test_upload_15_utterances_creates_recording(self, ami_data_dir: str) -> None:
        """Upload 15 utterances; verify a recording with summary is created."""
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable — start with docker-compose up")

        os.environ["MAX_UTTERANCES"] = "15"
        try:
            auth = DeviceAuthenticator()
            sim = Simulator(
                server_url=os.environ["DEVICE_SIM_SERVER_URL"],
                meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
                authenticator=auth,
            )
            sim.prepare(ami_data_dir)
            ids = sim.upload_all()
            assert len(ids) == 15, f"Expected 15 IDs, got {len(ids)}"

            # Poll with longer timeout for more utterances
            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=600.0,
            )

            assert all(s == "done" for s in status_map.values()), (
                f"Some utterances did not complete: {status_map}"
            )

            # Fetch recordings — should have at least one
            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert resp.status_code == 200
            recordings = resp.json()
            assert len(recordings) > 0, "Expected at least one recording"

            # Most recent recording should have a summary
            latest = recordings[-1]
            assert latest.get("summary"), f"Recording missing summary: {latest}"
            assert latest.get("category"), f"Recording missing category: {latest}"

            # Transcript segments should exist and be non-empty
            detail = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{latest['id']}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            ).json()
            segments = detail.get("transcript", {}).get("segments", [])
            assert len(segments) > 0, "Expected non-empty transcript segments"

        finally:
            os.environ.pop("MAX_UTTERANCES", None)
