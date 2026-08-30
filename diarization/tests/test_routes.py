"""Mock integration tests for diarization service routes."""

from unittest.mock import MagicMock, patch


def test_health():
    """Health endpoint returns healthy status."""
    # Import after conftest sets env vars
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diarization.routes import router

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_diarize_audio():
    """Diarize endpoint processes audio and returns segments."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diarization.routes import router

    app = FastAPI()
    app.include_router(router)

    fake_segments = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.5},
        {"speaker": "SPEAKER_01", "start": 2.5, "end": 5.0},
    ]

    mock_pipeline = MagicMock()
    mock_pipeline.diarize.return_value = fake_segments

    with patch("diarization.routes.pipeline", mock_pipeline):
        client = TestClient(app)
        response = client.post(
            "/diarize",
            files={"file": ("audio.opus", b"fake-opus-data", "audio/opus")},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["segments"]) == 2
    assert data["segments"][0]["speaker"] == "SPEAKER_00"
    assert data["segments"][0]["start"] == 0.0
    assert data["segments"][1]["speaker"] == "SPEAKER_01"


def test_diarize_empty_audio():
    """Diarize endpoint handles empty audio gracefully."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diarization.routes import router

    app = FastAPI()
    app.include_router(router)

    mock_pipeline = MagicMock()
    mock_pipeline.diarize.return_value = []

    with patch("diarization.routes.pipeline", mock_pipeline):
        client = TestClient(app)
        response = client.post(
            "/diarize",
            files={"file": ("empty.opus", b"", "audio/opus")},
        )

    assert response.status_code == 200
    assert response.json()["segments"] == []


def test_diarize_single_speaker():
    """Diarize endpoint with single speaker."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from diarization.routes import router

    app = FastAPI()
    app.include_router(router)

    mock_pipeline = MagicMock()
    mock_pipeline.diarize.return_value = [
        {"speaker": "SPEAKER_00", "start": 0.0, "end": 10.0},
    ]

    with patch("diarization.routes.pipeline", mock_pipeline):
        client = TestClient(app)
        response = client.post(
            "/diarize",
            files={"file": ("mono.opus", b"fake-audio", "audio/opus")},
        )

    assert response.status_code == 200
    segments = response.json()["segments"]
    assert len(segments) == 1
    assert segments[0]["end"] == 10.0
