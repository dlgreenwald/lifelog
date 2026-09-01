from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from lifelog.routes.transcription import router


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/internal/transcription")
    return TestClient(app)


def test_claim_returns_204_without_work():
    with patch(
        "lifelog.routes.transcription.db.claim_transcription_job",
        new_callable=AsyncMock,
        return_value=None,
    ):
        response = _client().post("/internal/transcription/claim")
    assert response.status_code == 204
    assert response.content == b""


def test_claim_serializes_job():
    job = {
        "id": 4,
        "session_id": 2,
        "window_start": datetime(2025, 1, 1, 10),
        "window_end": datetime(2025, 1, 1, 10, 10),
        "chunk_index": 0,
        "job_type": None,
        "result": None,
    }
    with patch(
        "lifelog.routes.transcription.db.claim_transcription_job",
        new_callable=AsyncMock,
        return_value=job,
    ):
        response = _client().post("/internal/transcription/claim")
    assert response.status_code == 200
    assert response.json()["job_type"] == "full"
    assert response.json()["window_start"] == "2025-01-01T10:00:00"


def test_stage_rejects_unknown_stage():
    response = _client().post("/internal/transcription/stage/4", json={"stage": "bad"})
    assert response.status_code == 422


def test_completion_persists_all_result_fields():
    with patch(
        "lifelog.routes.transcription.db.complete_transcription_job",
        new_callable=AsyncMock,
    ) as complete:
        response = _client().post(
            "/internal/transcription/complete/4",
            json={
                "segments": [],
                "full_transcript": {"segments": []},
                "speaker_map": {},
                "speaker_segments": [{"speaker": "SPEAKER_00"}],
                "utterance_spans": [],
            },
        )
    assert response.status_code == 200
    assert complete.await_args.args == (
        4,
        {
            "segments": [],
            "full_transcript": {"segments": []},
            "speaker_map": {},
            "utterance_spans": [],
            "speaker_segments": [{"speaker": "SPEAKER_00"}],
        },
    )


def test_quick_audio_returns_one_base64_segment():
    job = {
        "id": 4,
        "session_id": 2,
        "status": "processing",
        "job_type": "quick",
        "result": {"audio_filename": "a.enc"},
    }
    with (
        patch(
            "lifelog.routes.transcription.db.get_transcription_job",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch(
            "lifelog.routes.transcription._job_owner",
            new_callable=AsyncMock,
            return_value={"encryption_secret": "s", "key_salt": b"salt"},
        ),
        patch(
            "lifelog.routes.transcription.audio_crypto.decrypt_audio",
            return_value=b"audio",
        ),
    ):
        response = _client().get("/internal/transcription/audio/4")
    assert response.status_code == 200
    assert response.json()["audio_segments"] == ["YXVkaW8="]
    assert response.json()["timestamps"] == []


def test_audio_rejects_non_processing_job():
    with patch(
        "lifelog.routes.transcription.db.get_transcription_job",
        new_callable=AsyncMock,
        return_value={"status": "done"},
    ):
        response = _client().get("/internal/transcription/audio/4")
    assert response.status_code == 409
