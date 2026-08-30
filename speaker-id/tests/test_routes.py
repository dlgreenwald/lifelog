"""Unit tests for speaker-id utility functions and mock integration tests for routes."""

from unittest.mock import MagicMock, patch

import numpy as np

# --- Unit tests for cosine_similarity and match_voiceprint ---


def test_cosine_similarity_identical():
    """Identical vectors have similarity of 1.0."""
    from speaker_id.routes import cosine_similarity

    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert abs(cosine_similarity(a, b) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    """Orthogonal vectors have similarity of 0.0."""
    from speaker_id.routes import cosine_similarity

    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert abs(cosine_similarity(a, b)) < 1e-6


def test_cosine_similarity_opposite():
    """Opposite vectors have similarity of -1.0."""
    from speaker_id.routes import cosine_similarity

    a = np.array([1.0, 0.0])
    b = np.array([-1.0, 0.0])
    assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6


def test_cosine_similarity_partial():
    """Partial overlap returns expected similarity."""
    from speaker_id.routes import cosine_similarity

    a = np.array([1.0, 1.0])
    b = np.array([1.0, 0.0])
    expected = 1.0 / np.sqrt(2)
    assert abs(cosine_similarity(a, b) - expected) < 1e-6


def test_match_voiceprint_exact_match():
    """Exact embedding match returns the speaker name."""
    from speaker_id.routes import match_voiceprint

    embedding = np.array([1.0, 0.0, 0.0])
    voiceprints = [
        {"name": "Alice", "embedding": [1.0, 0.0, 0.0]},
    ]

    result = match_voiceprint(embedding, voiceprints, threshold=0.5)
    assert result == "Alice"


def test_match_voiceprint_below_threshold():
    """Dissimilar embedding returns Unknown."""
    from speaker_id.routes import match_voiceprint

    embedding = np.array([1.0, 0.0, 0.0])
    voiceprints = [
        {"name": "Alice", "embedding": [0.0, 1.0, 0.0]},
    ]

    result = match_voiceprint(embedding, voiceprints, threshold=0.9)
    assert result == "Unknown"


def test_match_voiceprint_best_match():
    """Best matching voiceprint is returned when multiple exist."""
    from speaker_id.routes import match_voiceprint

    embedding = np.array([1.0, 0.0, 0.0])
    voiceprints = [
        {"name": "Alice", "embedding": [0.0, 1.0, 0.0]},  # orthogonal
        {"name": "Bob", "embedding": [0.9, 0.1, 0.0]},  # very similar
    ]

    result = match_voiceprint(embedding, voiceprints, threshold=0.5)
    assert result == "Bob"


def test_match_voiceprint_empty_voiceprints():
    """No voiceprints returns Unknown."""
    from speaker_id.routes import match_voiceprint

    embedding = np.array([1.0, 0.0])
    result = match_voiceprint(embedding, [], threshold=0.5)
    assert result == "Unknown"


# --- Mock integration tests for routes ---


def test_identify_speakers():
    """Identify endpoint returns segments with Unknown names."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from speaker_id.routes import router

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.post(
        "/identify",
        json={
            "segments": [
                {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0},
                {"speaker": "SPEAKER_01", "start": 2.0, "end": 4.0},
            ],
            "voiceprints": [],
            "audio_format": "opus",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data["speakers"]) == 2
    assert data["speakers"][0]["name"] == "SPEAKER_00"
    assert data["speakers"][1]["name"] == "SPEAKER_01"


def test_identify_speakers_matches_voiceprint_from_audio():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from speaker_id.routes import router

    app = FastAPI()
    app.include_router(router)
    with (
        patch("speaker_id.routes._extract_segment_wav", return_value=b"wav"),
        patch(
            "speaker_id.routes.encoder.extract_embedding",
            return_value=np.array([1.0, 0.0]),
        ),
        patch("speaker_id.routes.match_voiceprint", return_value="Alice") as match,
    ):
        response = TestClient(app).post(
            "/identify",
            json={
                "segments": [
                    {"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "hi"}
                ],
                "audio_bytes": "YXVkaW8=",
                "audio_format": "wav",
                "voiceprints": [{"name": "Alice", "embedding": [1.0, 0.0]}],
            },
        )
    assert response.json()["speakers"][0]["name"] == "Alice"
    match.assert_called_once()


def test_identify_speakers_preserves_segment_data():
    """Identify endpoint preserves original segment fields."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from speaker_id.routes import router

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)
    response = client.post(
        "/identify",
        json={
            "segments": [
                {"speaker": "SPEAKER_00", "start": 1.5, "end": 3.2, "text": "Hello"},
            ],
            "voiceprints": [],
        },
    )

    assert response.status_code == 200
    seg = response.json()["speakers"][0]
    assert seg["start"] == 1.5
    assert seg["end"] == 3.2
    assert seg["text"] == "Hello"


def test_enroll_speaker():
    """Enroll endpoint extracts embedding and returns it."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from speaker_id.routes import router

    app = FastAPI()
    app.include_router(router)

    mock_embedding = np.array([0.1, 0.2, 0.3, 0.4])

    mock_encoder = MagicMock()
    mock_encoder.extract_embedding.return_value = mock_embedding

    with patch("speaker_id.routes.encoder", mock_encoder):
        with patch("speaker_id.routes.opus_to_wav", return_value=b"fake-wav"):
            client = TestClient(app)
            response = client.post(
                "/enroll?name=Alice",
                files={"file": ("voice.opus", b"fake-opus", "audio/opus")},
            )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Alice"
    assert len(data["embedding"]) == 4
    assert abs(data["embedding"][0] - 0.1) < 1e-6
