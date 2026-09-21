"""Unit tests for lifelog.routes.upload — helper functions and module constants."""

import pytest

# ── Module constants ────────────────────────────────────────────────────────────


class TestUploadConstants:
    def test_max_chunk_size_is_10mb(self):
        from lifelog.routes.upload import MAX_CHUNK_SIZE

        assert MAX_CHUNK_SIZE == 10 * 1024 * 1024

    def test_utterance_ttl_is_30_minutes(self):
        from lifelog.routes.upload import UTTERANCE_TTL

        assert UTTERANCE_TTL == 1800


# ── _opus_sample_rate ───────────────────────────────────────────────────────────


class TestOpusSampleRate:
    def test_too_short_bytes_returns_none(self):
        from lifelog.routes.upload import _opus_sample_rate

        assert _opus_sample_rate(b"short") is None

    def test_subprocess_returns_sample_rate(self):
        """Test that _opus_sample_rate parses opusinfo output correctly."""
        from unittest.mock import MagicMock, patch

        mock_result = MagicMock()
        mock_result.stdout = "Original sample rate: 48000 Hz\nChannels: 1"
        mock_result.stderr = ""

        mock_subprocess = MagicMock()
        mock_subprocess.run.return_value = mock_result

        mock_tempfile = MagicMock()
        mock_tempfile.return_value.__enter__ = lambda s: (
            setattr(s, "name", "/tmp/test.opus") or s
        )
        mock_tempfile.return_value.__aexit__ = lambda *a: None

        mock_os = MagicMock()

        # Replace the local imports inside _opus_sample_rate via sys.modules
        import sys

        with patch.dict(
            sys.modules,
            {
                "subprocess": mock_subprocess,
                "tempfile": mock_tempfile,
                "os": mock_os,
            },
        ):
            # Re-import to pick up the mocked modules
            from lifelog.routes.upload import _opus_sample_rate

            result = _opus_sample_rate(b"x" * 200)

        assert result == 48000
        mock_subprocess.run.assert_called_once()

    def test_opusinfo_unavailable_returns_none(self):
        from unittest.mock import patch

        from lifelog.routes.upload import _opus_sample_rate

        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert _opus_sample_rate(b"x" * 200) is None


# ── _evict_stale_utterances ───────────────────────────────────────────────────


class TestEvictStaleUtterances:
    def test_no_eviction_when_fresh(self):
        from lifelog.routes.upload import _active_utterances, _evict_stale_utterances

        # Reset state
        _active_utterances.clear()

        # Add a fresh entry
        _active_utterances[1] = {100: {"server_id": 5, "last_seen": 1000}}

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("lifelog.routes.upload._current_epoch", lambda: 1500)
            _evict_stale_utterances()

        assert 1 in _active_utterances
        assert 100 in _active_utterances[1]

        _active_utterances.clear()

    def test_evicts_expired_entries(self):
        from lifelog.routes.upload import _active_utterances, _evict_stale_utterances

        _active_utterances.clear()
        # Entry last seen at timestamp 100, TTL = 1800
        _active_utterances[1] = {100: {"server_id": 5, "last_seen": 100}}

        with pytest.MonkeyPatch.context() as mp:
            # Current time is 1900 — entry is 1800 seconds old, exactly at TTL boundary
            # Still present (not > TTL). Advance to 1901 — now expired.
            mp.setattr("lifelog.routes.upload._current_epoch", lambda: 1901)
            _evict_stale_utterances()

        assert 1 not in _active_utterances

    def test_evicts_expired_leaves_valid(self):
        from lifelog.routes.upload import _active_utterances, _evict_stale_utterances

        _active_utterances.clear()
        # User 1: expired entry
        _active_utterances[1] = {100: {"server_id": 1, "last_seen": 100}}
        # User 2: fresh entry
        _active_utterances[2] = {200: {"server_id": 2, "last_seen": 5000}}

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("lifelog.routes.upload._current_epoch", lambda: 6000)
            _evict_stale_utterances()

        assert 1 not in _active_utterances
        assert 2 in _active_utterances
        assert 200 in _active_utterances[2]

        _active_utterances.clear()

    def test_empty_active_utterances_noop(self):
        from lifelog.routes.upload import _active_utterances, _evict_stale_utterances

        _active_utterances.clear()
        _evict_stale_utterances()  # Should not raise
