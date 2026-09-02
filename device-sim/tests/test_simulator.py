"""Integration tests for the device simulator.

These tests verify the simulator's core behavior (auth, slicing, encoding, upload).
Transcription pipeline results are verified manually or in e2e tests, not here.
"""

from __future__ import annotations

import os

from device_sim.auth import DeviceAuthenticator
from device_sim.simulator import Simulator


def _make_sim(ami_data_dir: str) -> Simulator:
    auth = DeviceAuthenticator()
    return Simulator(
        server_url=os.environ["DEVICE_SIM_SERVER_URL"],
        meeting_id=os.environ.get("MEETING_ID", "EN2001a"),
        authenticator=auth,
    )


class TestSimulator:
    def test_auth_token_acquired(self, ami_data_dir, test_oidc_sub):
        """Authenticator obtains a valid OIDC token."""
        auth = DeviceAuthenticator()
        token = auth.get_token()
        assert token, "Expected a non-empty access token"
        assert len(token) > 50, "OIDC tokens are typically long JWTs"
        # Token sub should match the configured test user sub
        import base64
        import json
        payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
        assert payload["sub"] == test_oidc_sub, (
            f"Token sub {payload['sub']} does not match test user sub {test_oidc_sub}"
        )

    def test_slice_and_encode_small(self, ami_data_dir, test_oidc_sub):
        """Small slice (5 utterances) can be sliced, encoded, and uploaded successfully."""
        os.environ["MAX_UTTERANCES"] = "5"
        try:
            sim = _make_sim(ami_data_dir)
            sim.prepare(ami_data_dir)
            assert len(sim.utterances) == 5, f"Expected 5 utterances, got {len(sim.utterances)}"

            ids = sim.upload_all()
            assert len(ids) == 5, f"Expected 5 upload IDs, got {len(ids)}"
            assert all(isinstance(i, int) for i in ids), "Server IDs should be integers"
        finally:
            os.environ.pop("MAX_UTTERANCES", None)

    def test_truncated_meeting_upload(self, ami_data_dir, test_oidc_sub):
        """First 15 utterances are uploaded with correct server IDs returned."""
        os.environ["MAX_UTTERANCES"] = "15"
        try:
            sim = _make_sim(ami_data_dir)
            sim.prepare(ami_data_dir)
            ids = sim.upload_all()

            assert len(ids) == 15, f"Expected 15 IDs, got {len(ids)}"
            assert all(isinstance(i, int) for i in ids)
        finally:
            os.environ.pop("MAX_UTTERANCES", None)

    def test_silence_artifact_handling(self, ami_data_dir, test_oidc_sub):
        """Silence artifacts are encoded without error and uploaded successfully."""
        os.environ["SILENCE_INSERT_EVERY"] = "5"
        os.environ["SILENCE_INSERT_PROBABILITY"] = "1.0"
        os.environ["MAX_UTTERANCES"] = "10"
        try:
            sim = _make_sim(ami_data_dir)
            sim.prepare(ami_data_dir)

            # Should include silence utterances (is_silence=True)
            silence_utts = [u for u in sim.utterances if u.is_silence]
            assert len(silence_utts) > 0, "Expected at least one silence utterance"

            ids = sim.upload_all()
            assert len(ids) == len(sim.utterances), "All utterances should upload"
        finally:
            os.environ.pop("SILENCE_INSERT_EVERY", None)
            os.environ.pop("SILENCE_INSERT_PROBABILITY", None)
            os.environ.pop("MAX_UTTERANCES", None)

    def test_device_reboot_all_utterances_same_session(self, ami_data_dir, test_oidc_sub):
        """All utterances from a meeting belong to one session (no mid-session reboot)."""
        os.environ["MAX_UTTERANCES"] = "10"
        try:
            sim = _make_sim(ami_data_dir)
            sim.prepare(ami_data_dir)
            ids = sim.upload_all()

            assert len(ids) == len(sim.utterances), "All utterances should upload"
        finally:
            os.environ.pop("MAX_UTTERANCES", None)

    def test_auth_refresh_on_401(self, ami_data_dir, test_oidc_sub, monkeypatch):
        """Upload succeeds after one re-auth round-trip on 401."""
        import httpx

        original_post = httpx.Client.post
        call_count = [0]

        def patched_post(self, url, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                resp = httpx.Response(401, content=b'{"detail": "Invalid token"}')
                return resp
            return original_post(self, url, **kwargs)

        monkeypatch.setattr(httpx.Client, "post", patched_post)

        os.environ["MAX_UTTERANCES"] = "2"
        try:
            sim = _make_sim(ami_data_dir)
            sim.prepare(ami_data_dir)
            ids = sim.upload_all()
            assert len(ids) == 2, f"Expected 2 IDs after retry, got {len(ids)}"
            assert call_count[0] >= 2, f"Expected at least 2 POST attempts, got {call_count[0]}"
        finally:
            os.environ.pop("MAX_UTTERANCES", None)
