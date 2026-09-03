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
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from device_sim.auth import DeviceAuthenticator
from device_sim.simulator import Simulator


def _server_reachable(url: str) -> bool:
    """Check if the server is reachable."""
    try:
        resp = httpx.get(f"{url}/health", timeout=10, verify=False)
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
    """Poll utterance status until all are done/failed or timeout."""
    start = time.monotonic()
    pending = set(utterance_ids)
    status: dict[int, str] = {}

    while pending:
        if time.monotonic() - start > timeout_s:
            raise TimeoutError(
                f"Timed out after {timeout_s}s waiting for utterances: {pending}"
            )
        for uid in list(pending):
            try:
                resp = httpx.get(
                    f"{server_url}/api/v1/utterance/{uid}/status",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=30,
                    verify=False,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.NetworkError):
                continue  # Transient error — retry
            if resp.status_code == 200:
                data = resp.json()
                s = data.get("status", "unknown")
                if s in ("done", "failed", "unknown"):
                    status[uid] = s
                    pending.discard(uid)
        if pending:
            time.sleep(poll_interval_s)

    return status


def _tokenize(text: str) -> set[str]:
    """Lowercase, strip non-alphanumeric, return word set."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return set(text.split())


def _content_words(text: str) -> set[str]:
    """Return content words: tokenized, lowercase, ≥ 3 chars, non-stopword."""
    stopwords = {
        "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
        "your", "yours", "yourself", "yourselves", "he", "him", "his",
        "himself", "she", "her", "hers", "herself", "it", "its", "itself",
        "they", "them", "their", "theirs", "themselves", "what", "which",
        "who", "whom", "this", "that", "these", "those", "am", "is", "are",
        "was", "were", "be", "been", "being", "have", "has", "had", "having",
        "do", "does", "did", "doing", "a", "an", "the", "and", "but", "if",
        "or", "because", "as", "until", "while", "of", "at", "by", "for",
        "with", "about", "against", "between", "into", "through", "during",
        "before", "after", "above", "below", "to", "from", "up", "down",
        "in", "out", "on", "off", "over", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why", "how",
        "all", "each", "few", "more", "most", "other", "some", "such",
        "no", "nor", "not", "only", "own", "same", "so", "than", "too",
        "very", "s", "t", "can", "will", "just", "don", "should", "now",
        "d", "ll", "m", "o", "re", "ve", "y", "ain", "aren", "couldn",
        "didn", "doesn", "hadn", "hasn", "haven", "isn", "ma", "mightn",
        "mustn", "needn", "shan", "shouldn", "wasn", "weren", "won", "wouldn",
        "yeah", "yes", "oh", "okay", "ok", "um", "uh", "er", "ah", "hm",
        "hmm", "like", "well", "right", "got", "get", "go", "going",
        "know", "see", "say", "said", "think", "thing", "things",
        "one", "two", "three", "actually", "maybe", "probably", "really",
        "quite", "rather", "also", "even", "still", "yet", "already",
    }
    tokens = _tokenize(text)
    return {w for w in tokens if len(w) >= 3 and w not in stopwords}


def _ami_transcript_for_range(
    annotations_zip_path: str,
    meeting_id: str,
    start_s: float,
    end_s: float,
) -> str:
    """Return the AMI manual transcript for a time range across all channels."""
    words: list[tuple[float, str]] = []

    with zipfile.ZipFile(annotations_zip_path, "r") as zf:
        word_files = [
            n for n in zf.namelist()
            if f"/{meeting_id}." in n and n.endswith(".words.xml")
        ]
        for name in word_files:
            content = zf.read(name).decode("ISO-8859-1", errors="replace")
            root = ET.fromstring(content)
            for w_elem in root.findall(".//w"):
                w_start = float(w_elem.attrib.get("starttime", -1))
                w_end = float(w_elem.attrib.get("endtime", -1))
                text = (w_elem.text or "").strip()
                if w_start < end_s and w_end > start_s and text:
                    words.append((w_start, text))

    words.sort(key=lambda x: x[0])
    return " ".join(w for _, w in words)


def _find_contiguous_block(
    utterances: list,
    min_utts: int = 3,
    max_gap_s: float = 5.0,
) -> list:
    """Find the longest contiguous block of utterances (gap ≤ max_gap_s)."""
    if not utterances:
        return []

    blocks: list[list] = []
    cur = [utterances[0]]
    for u in utterances[1:]:
        if u.start_s - cur[-1].end_s <= max_gap_s:
            cur.append(u)
        else:
            if len(cur) >= min_utts:
                blocks.append(cur)
            cur = [u]
    if len(cur) >= min_utts:
        blocks.append(cur)

    if not blocks:
        return []
    return max(blocks, key=lambda b: len(b))


def _today() -> str:
    """Return today's date as YYYY-MM-DD string in local timezone."""
    return datetime.now().astimezone().date().isoformat()


# Env vars consumed by Simulator/slicer — cleared after each test to prevent
# test-case pollution when tests run in the same subprocess.
_SIM_ENV_VARS = (
    "HEADSET_CHANNEL",
    "MIN_UTTERANCE_DURATION",
    "MAX_UTTERANCES",
    "UPLOAD_INTERVAL_SECONDS",
)


class TestPipeline:
    """End-to-end pipeline tests: upload → transcribe → verify transcript."""

    @pytest.mark.integration
    def test_upload_5_utterances_transcribed(self, ami_data_dir: str) -> None:
        """Upload at least 5 utterances; verify transcription completes and transcript is non-empty."""
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable — start with docker-compose up")

        for k in _SIM_ENV_VARS:
            os.environ.pop(k, None)
        # MAX_UTTERANCES=20 provides enough candidates so that after
        # MIN_UTTERANCE_DURATION=3 filters out zero-duration micro-segments
        # (from overlapping multi-speaker NITE segments), ≥ 5 still survive.
        os.environ["MAX_UTTERANCES"] = "20"
        os.environ["MIN_UTTERANCE_DURATION"] = "3"
        try:
            auth = DeviceAuthenticator()
            sim = Simulator(
                server_url=os.environ["DEVICE_SIM_SERVER_URL"],
                meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
                authenticator=auth,
            )
            sim.prepare(ami_data_dir)
            assert len(sim.utterances) >= 5, (
                f"Expected ≥ 5 utterances after duration filter, got {len(sim.utterances)}. "
                "Adjust MAX_UTTERANCES or MIN_UTTERANCE_DURATION."
            )

            ids = sim.upload_all()
            assert len(ids) >= 5, f"Expected ≥ 5 server IDs, got {len(ids)}"

            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=300.0,
            )

            assert all(s == "done" for s in status_map.values()), (
                f"Some utterances did not complete successfully: {status_map}"
            )

            today_str = _today()
            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings/{today_str}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
                verify=False,
            )
            assert resp.status_code == 200, f"Failed to fetch recordings for {today_str}: {resp.text}"

            recordings = resp.json().get("recordings", [])
            assert len(recordings) > 0, (
                f"Expected at least one recording after transcription (date={today_str})"
            )

            latest = recordings[-1]
            detail_resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{latest['id']}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
                verify=False,
            )
            assert detail_resp.status_code == 200
            recording = detail_resp.json()
            segments = recording.get("transcript", {}).get("segments", [])
            assert len(segments) > 0, f"Expected non-empty transcript segments, got: {segments}"

            for seg in segments:
                assert seg.get("text"), f"Segment missing text: {seg}"
                # speaker is optional — WhisperX may not assign a speaker to short segments

        finally:
            for k in _SIM_ENV_VARS:
                os.environ.pop(k, None)

    @pytest.mark.integration
    def test_upload_15_utterances_creates_recording(self, ami_data_dir: str) -> None:
        """Upload at least 15 utterances; verify a recording with summary is created."""
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable")

        for k in _SIM_ENV_VARS:
            os.environ.pop(k, None)
        # MAX_UTTERANCES=50 provides enough candidates so that after
        # MIN_UTTERANCE_DURATION=3 filtering, ≥ 15 survive.
        os.environ["MAX_UTTERANCES"] = "50"
        os.environ["MIN_UTTERANCE_DURATION"] = "3"
        try:
            auth = DeviceAuthenticator()
            sim = Simulator(
                server_url=os.environ["DEVICE_SIM_SERVER_URL"],
                meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
                authenticator=auth,
            )
            sim.prepare(ami_data_dir)
            ids = sim.upload_all()
            assert len(ids) >= 15, f"Expected ≥ 15 IDs, got {len(ids)}"

            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=600.0,
            )

            assert all(s == "done" for s in status_map.values()), (
                f"Some utterances did not complete: {status_map}"
            )

            today_str = _today()
            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings/{today_str}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
                verify=False,
            )
            assert resp.status_code == 200, f"Failed to fetch recordings for {today_str}: {resp.text}"
            recordings = resp.json().get("recordings", [])
            assert len(recordings) > 0, f"No recordings found for today ({today_str})"

            latest = recordings[-1]
            assert latest.get("summary"), f"Recording missing summary: {latest}"
            assert latest.get("category"), f"Recording missing category: {latest}"

            detail = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{latest['id']}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
                verify=False,
            ).json()
            segments = detail.get("transcript", {}).get("segments", [])
            assert len(segments) > 0, "Expected non-empty transcript segments"

        finally:
            for k in _SIM_ENV_VARS:
                os.environ.pop(k, None)


class TestTranscriptAccuracy:
    """Transcript quality validation using AMI manual transcripts as ground truth.

    Strategy — keyword overlap (Jaccard):
    - Extract content words (≥3 chars, non-stopword) from the AMI manual
      transcript for the uploaded time window.
    - Extract content words from the WhisperX transcript.
    - Compute Jaccard = |GT_words ∩ AC_words| / |GT_words|.
    - Require ≥ 15% overlap. This tolerates ASR errors, cross-speaker bleed,
      and timing misalignment while detecting off-topic or failed transcription.
    """

    @pytest.mark.integration
    def test_transcribed_text_matches_ground_truth(self, ami_data_dir: str) -> None:
        """Upload contiguous Channel 4 utterances; verify keyword overlap with AMI ground truth.

        Channel 4 (MEO069) is selected for its utterance count. A contiguous block
        of ≥ 3 utterances (gap ≤ 5s) is located dynamically. Ground truth is the
        AMI manual transcript for that time window; transcript is the WhisperX output.
        """
        if not _server_reachable(os.environ["DEVICE_SIM_SERVER_URL"]):
            pytest.skip("Server not reachable")

        for k in _SIM_ENV_VARS:
            os.environ.pop(k, None)
        # UPLOAD_INTERVAL_SECONDS=0 disables real-time replay delays so the test
        # runs in seconds rather than minutes. MAX_UTTERANCES=20 gives enough
        # utterances for a good contiguous block without excess upload time.
        os.environ["HEADSET_CHANNEL"] = "4"
        os.environ["MIN_UTTERANCE_DURATION"] = "5"
        os.environ["MAX_UTTERANCES"] = "20"
        try:
            auth = DeviceAuthenticator()
            sim = Simulator(
                server_url=os.environ["DEVICE_SIM_SERVER_URL"],
                meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
                authenticator=auth,
                device_start_ahead_seconds=0.0,
            )
            sim.upload_interval = 0.0
            sim.prepare(ami_data_dir)

            block = _find_contiguous_block(sim.utterances, min_utts=3, max_gap_s=5.0)
            assert len(block) >= 3, (
                f"Need ≥ 3 contiguous utterances, got {len(block)}. "
                "Check HEADSET_CHANNEL and MIN_UTTERANCE_DURATION settings."
            )

            # Use only the block for this test
            sim.utterances = block

            total_start = block[0].start_s
            total_end = block[-1].end_s

            annotations_zip = str(Path(ami_data_dir).parent / "EN2001a" / "annotations.zip")
            combined_ground_truth = _ami_transcript_for_range(
                annotations_zip, sim.meeting_id, total_start, total_end
            )

            gt_words = _content_words(combined_ground_truth)
            assert len(gt_words) >= 5, (
                f"Ground truth too sparse: only {len(gt_words)} content words "
                f"in [{total_start:.0f}-{total_end:.0f}]. Need ≥ 5 for meaningful test."
            )

            ids = sim.upload_all()
            assert len(ids) >= 3, f"Expected ≥ 3 utterances in block, got {len(ids)}"

            status_map = _poll_until_status(
                os.environ["DEVICE_SIM_SERVER_URL"],
                auth.get_token(),
                ids,
                timeout_s=300.0,
            )
            assert all(s == "done" for s in status_map.values()), str(status_map)

            today_str = _today()
            resp = httpx.get(
                f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recordings/{today_str}",
                headers={"Authorization": f"Bearer {auth.get_token()}"},
                timeout=10,
                verify=False,
            )
            assert resp.status_code == 200
            recordings = resp.json().get("recordings", [])
            assert len(recordings) > 0, f"No recordings for {today_str}"

            recording = None
            for rec in reversed(recordings):
                detail = httpx.get(
                    f"{os.environ['DEVICE_SIM_SERVER_URL']}/api/v1/dashboard/recording/{rec['id']}",
                    headers={"Authorization": f"Bearer {auth.get_token()}"},
                    timeout=10,
                    verify=False,
                ).json()
                if detail.get("transcript", {}).get("segments"):
                    recording = detail
                    break

            assert recording is not None, "No recording with transcript segments found"
            segments = recording.get("transcript", {}).get("segments", [])
            combined_actual = " ".join(seg.get("text", "") for seg in segments)
            ac_words = _content_words(combined_actual)

            overlap = gt_words & ac_words
            jaccard = len(overlap) / len(gt_words) if gt_words else 0.0

            print(f"\n  Block: [{total_start:.0f}-{total_end:.0f}] {len(block)} utts")
            print(f"  Keyword overlap (Jaccard): {jaccard:.0%} ({len(overlap)}/{len(gt_words)} GT words)")
            print(f"  Overlap sample: {sorted(overlap)[:15]}")
            print(f"  GT sample:      {sorted(gt_words)[:15]}")
            print(f"  Actual words:   {len(ac_words)} content words total")

            assert jaccard >= 0.15, (
                f"Keyword overlap {jaccard:.0%} < 15%. "
                f"GT ({len(gt_words)} words): {sorted(gt_words)[:20]} | "
                f"Overlap ({len(overlap)}): {sorted(overlap)[:20]}"
            )

        finally:
            for k in _SIM_ENV_VARS:
                os.environ.pop(k, None)
