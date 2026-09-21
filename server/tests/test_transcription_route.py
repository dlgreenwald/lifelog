"""Unit tests for lifelog.routes.transcription — helpers and Pydantic models."""

import pytest
from pydantic import ValidationError

from lifelog.routes.transcription import (
    _ALLOWED_STAGES,
    JobError,
    JobResult,
    StageUpdate,
    UtteranceSpan,
    _iso,
    _json_value,
)

# ── _iso ───────────────────────────────────────────────────────────────────────


class TestIso:
    def test_datetime_returns_iso_string(self):
        from datetime import datetime

        dt = datetime(2026, 9, 20, 14, 30, 0)
        assert _iso(dt) == "2026-09-20T14:30:00"

    def test_none_returns_none(self):
        assert _iso(None) is None


# ── _json_value ───────────────────────────────────────────────────────────────


class TestJsonValue:
    def test_string_returns_parsed_json(self):
        result = _json_value('{"key": "value"}', {})
        assert result == {"key": "value"}

    def test_invalid_json_returns_default(self):
        result = _json_value("not json", {"fallback": True})
        assert result == {"fallback": True}

    def test_non_string_returns_value(self):
        result = _json_value({"already": "dict"}, {})
        assert result == {"already": "dict"}

    def test_none_returns_default(self):
        result = _json_value(None, "default")
        assert result == "default"


# ── _ALLOWED_STAGES ────────────────────────────────────────────────────────────


class TestAllowedStages:
    def test_expected_stages_present(self):
        assert "queued" in _ALLOWED_STAGES
        assert "transcribing" in _ALLOWED_STAGES
        assert "diarizing" in _ALLOWED_STAGES
        assert "done" in _ALLOWED_STAGES

    def test_no_forbidden_stages(self):
        assert "invalid" not in _ALLOWED_STAGES
        assert "failed" not in _ALLOWED_STAGES


# ── StageUpdate model ──────────────────────────────────────────────────────────


class TestStageUpdate:
    def test_valid_stage(self):
        result = StageUpdate(stage="transcribing")
        assert result.stage == "transcribing"

    def test_invalid_stage_still_parses(self):
        # Pydantic doesn't validate enum here — the route does
        result = StageUpdate(stage="invalid")
        assert result.stage == "invalid"


# ── UtteranceSpan model ───────────────────────────────────────────────────────


class TestUtteranceSpan:
    def test_valid(self):
        span = UtteranceSpan(utterance_id=1, start=0.0, end=5.5)
        assert span.utterance_id == 1
        assert span.start == 0.0
        assert span.end == 5.5

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            UtteranceSpan(utterance_id=1)  # missing start and end


# ── JobResult model ────────────────────────────────────────────────────────────


class TestJobResult:
    def test_valid_minimal(self):
        result = JobResult(
            segments=[{"text": "hello", "speaker": "Alice", "start": 0.0, "end": 1.5}],
            full_transcript={},
            speaker_map={},
        )
        assert len(result.segments) == 1

    def test_full_fields(self):
        result = JobResult(
            segments=[{"text": "hello"}],
            full_transcript={"segments": []},
            speaker_segments=[{"speaker": "Alice", "text": "hello"}],
            speaker_map={"0": "Alice"},
            utterance_spans=[UtteranceSpan(utterance_id=1, start=0.0, end=1.5)],
            utterance_ids=[1],
        )
        assert result.speaker_segments[0]["speaker"] == "Alice"
        assert result.utterance_ids == [1]

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            JobResult()  # missing required fields

    def test_utterance_spans_validation(self):
        # utterance_spans must be list of UtteranceSpan
        result = JobResult(
            segments=[],
            full_transcript={},
            speaker_map={},
            utterance_spans=[{"utterance_id": 1, "start": 0.0, "end": 1.5}],
        )
        assert len(result.utterance_spans) == 1


# ── JobError model ─────────────────────────────────────────────────────────────


class TestJobError:
    def test_valid(self):
        err = JobError(error="WhisperX crashed")
        assert err.error == "WhisperX crashed"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            JobError()
