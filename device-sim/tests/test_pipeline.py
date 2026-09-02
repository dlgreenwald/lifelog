"""End-to-end pipeline integration tests.

These tests upload utterances via the device simulator, wait for the
transcription pipeline to complete, and verify the resulting transcripts.

Requires a live server stack (docker-compose up) with transcription-worker
and speaker-id services. Tests are skipped if the server is unreachable.
"""

from __future__ import annotations

import os
import re
import time

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


def _tokenize(text: str) -> list[str]:
    """Lowercase, strip non-alphanumeric characters, split on whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return text.split()


def _word_levenshtein(s: list[str], t: list[str]) -> int:
    """Word-level Levenshtein edit distance."""
    m, n = len(s), len(t)
    dp: list[list[int]] = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s[i - 1] == t[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[m][n]


def _word_accuracy(ground_truth: str, actual: str) -> float:
    """Word-order-aware accuracy: 1 - (edit_distance / max(len_gt, len_actual)).

    Returns 0.0 – 1.0. A score of 1.0 means identical word sequences.
    Accounts for insertions, deletions, and substitutions.
    """
    gt_tokens = _tokenize(ground_truth)
    ac_tokens = _tokenize(actual)
    if not gt_tokens and not ac_tokens:
        return 1.0
    if not gt_tokens or not ac_tokens:
        return 0.0
    dist = _word_levenshtein(gt_tokens, ac_tokens)
    max_len = max(len(gt_tokens), len(ac_tokens))
    return max(0.0, 1.0 - (dist / max_len))


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

            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=300.0,
            )

            assert all(s == "done" for s in status_map.values()), (
                f"Some utterances did not complete successfully: {status_map}"
            )

            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert resp.status_code == 200, f"Failed to fetch recordings: {resp.text}"

            recordings = resp.json()
            assert len(recordings) > 0, "Expected at least one recording after transcription"

            latest = recordings[-1]
            detail_resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{latest['id']}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert detail_resp.status_code == 200
            recording = detail_resp.json()
            segments = recording.get("transcript", {}).get("segments", [])
            assert len(segments) > 0, f"Expected non-empty transcript segments, got: {segments}"

            for seg in segments:
                assert seg.get("text"), f"Segment missing text: {seg}"
                assert seg.get("speaker"), f"Segment missing speaker: {seg}"

        finally:
            os.environ.pop("MAX_UTTERANCES", None)

    @pytest.mark.integration
    def test_upload_15_utterances_creates_recording(self, ami_data_dir: str) -> None:
        """Upload 15 utterances; verify a recording with summary is created."""
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable")

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

            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=600.0,
            )

            assert all(s == "done" for s in status_map.values()), (
                f"Some utterances did not complete: {status_map}"
            )

            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert resp.status_code == 200
            recordings = resp.json()
            assert len(recordings) > 0, "Expected at least one recording"

            latest = recordings[-1]
            assert latest.get("summary"), f"Recording missing summary: {latest}"
            assert latest.get("category"), f"Recording missing category: {latest}"

            detail = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{latest['id']}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            ).json()
            segments = detail.get("transcript", {}).get("segments", [])
            assert len(segments) > 0, "Expected non-empty transcript segments"

        finally:
            os.environ.pop("MAX_UTTERANCES", None)


class TestTranscriptAccuracy:
    """Verify transcribed text matches AMI ground truth within acceptable error bounds."""

    @pytest.mark.integration
    def test_transcribed_text_matches_ground_truth(self, ami_data_dir: str) -> None:
        """Upload 5 utterances; compare each against AMI ground truth transcription.

        Uses word-level Levenshtein edit distance to check that the transcribed
        word sequence matches the reference word sequence. Accounts for:
        - Insertions, deletions, and substitutions (not just missing words)
        - Word order (a transposed phrase scores lower)
        - Minor ASR errors (single-word substitutions don't destroy the score)

        Require ≥ 50% word-sequence accuracy across non-empty utterances to catch
        gross failures (silent audio, model unload, wrong language).
        """
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable")

        os.environ["MAX_UTTERANCES"] = "5"
        try:
            auth = DeviceAuthenticator()
            sim = Simulator(
                server_url=os.environ["DEVICE_SIM_SERVER_URL"],
                meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
                authenticator=auth,
            )
            sim.prepare(ami_data_dir)

            ground_truth = {u.index: u.transcript for u in sim.utterances}

            ids = sim.upload_all()
            assert len(ids) == 5

            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=300.0,
            )
            assert all(s == "done" for s in status_map.values()), str(status_map)

            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
            )
            assert resp.status_code == 200
            recordings = resp.json()

            # Find the most recent recording with transcript segments
            recording = None
            for rec in reversed(recordings):
                detail_resp = httpx.get(
                    f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{rec['id']}",
                    headers={"Authorization": f"Bearer {auth.get_token()}"},
                    timeout=10,
                )
                detail = detail_resp.json()
                segments = detail.get("transcript", {}).get("segments", [])
                if segments:
                    recording = detail
                    break

            assert recording is not None, "No recording found with transcript segments"
            segments = recording.get("transcript", {}).get("segments", [])
            actual_text = " ".join(seg.get("text", "") for seg in segments)

            # Per-utterance word-sequence accuracy
            results: list[tuple[int, str, float]] = []
            for idx, gt_text in ground_truth.items():
                stripped = gt_text.strip()
                if not stripped or stripped in ("...", ".", "-"):
                    continue
                rate = _word_accuracy(gt_text, actual_text)
                results.append((idx, gt_text, rate))

            overall_rate = sum(r[2] for r in results) / len(results) if results else 0.0
            assert overall_rate >= 0.50, (
                f"Transcript accuracy {overall_rate:.0%} < 50% threshold. "
                f"Per-utterance: {[(idx, f'{rate:.0%}') for idx, _, rate in results]}"
            )

            # Print per-utterance detail
            for idx, gt_text, rate in results:
                gt_tokens = _tokenize(gt_text)
                ac_tokens = _tokenize(actual_text)
                dist = _word_levenshtein(gt_tokens, ac_tokens)
                print(f"\n  Utterance {idx}: {rate:.0%} accuracy | edit dist={dist} | GT: {gt_text[:60]}")
                print(f"    GT tokens:      {' '.join(gt_tokens)[:80]}")
                print(f"    Actual tokens:  {' '.join(ac_tokens)[:80]}")

        finally:
            os.environ.pop("MAX_UTTERANCES", None)
