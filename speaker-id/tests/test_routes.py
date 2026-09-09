"""Unit tests for speaker-id utility functions and mock integration tests for routes."""

import base64
from unittest.mock import patch

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


def test_compute_centroid_normalizes_before_and_after_mean():
    """Centroid is the renormalized mean of L2-normalized embeddings."""
    from speaker_id.routes import compute_centroid

    embeddings = [np.array([3.0, 0.0, 0.0]), np.array([0.0, 4.0, 0.0])]
    centroid = compute_centroid(embeddings)

    # normalize([[3,0,0],[0,4,0]]) = [[1,0,0],[0,1,0]]; mean=[0.5,0.5,0];
    # renormalized -> [0.7071, 0.7071, 0] — NOT the raw mean [0.6, 0.8, 0].
    expected = np.array([0.70710678, 0.70710678, 0.0])
    np.testing.assert_allclose(centroid, expected, atol=1e-6)


def test_match_centroid_best_above_threshold():
    """Best similarity above threshold wins and carries speaker_id."""
    from speaker_id.routes import match_centroid

    centroid = np.array([1.0, 0.0])
    voiceprints = [
        {"speaker_id": 7, "name": "Alice", "embedding": [0.0, 1.0]},
        {"speaker_id": 3, "name": "Bob", "embedding": [1.0, 0.0]},
    ]
    match = match_centroid(centroid, voiceprints, threshold=0.75)
    assert match is not None
    assert match["speaker_id"] == 3
    assert match["name"] == "Bob"
    assert abs(match["similarity"] - 1.0) < 1e-6


def test_match_centroid_no_match_below_threshold():
    """No similarity above threshold returns None."""
    from speaker_id.routes import match_centroid

    centroid = np.array([1.0, 0.0])
    voiceprints = [{"speaker_id": 7, "name": "Alice", "embedding": [0.0, 1.0]}]
    assert match_centroid(centroid, voiceprints, threshold=0.75) is None


def _resolve_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from speaker_id.routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_resolve_matched():
    """Resolve returns centroid and best matching speaker_id."""
    with (
        patch(
            "speaker_id.routes.encoder.extract_embedding",
            return_value=np.array([3.0, 0.0]),
        ),
        patch("speaker_id.routes.opus_to_wav", return_value=b"wav"),
    ):
        response = _resolve_client().post(
            "/resolve",
            json={
                "audio_b64": [base64.b64encode(b"fake-opus").decode()],
                "voiceprints": [
                    {"speaker_id": 7, "name": "Alice", "embedding": [1.0, 0.0]}
                ],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["match"]["speaker_id"] == 7
    assert data["match"]["name"] == "Alice"
    np.testing.assert_allclose(data["centroid"], [1.0, 0.0], atol=1e-6)


def test_resolve_unmatched():
    """Resolve with no similar voiceprint returns match None."""
    with (
        patch(
            "speaker_id.routes.encoder.extract_embedding",
            return_value=np.array([0.0, 5.0]),
        ),
        patch("speaker_id.routes.opus_to_wav", return_value=b"wav"),
    ):
        response = _resolve_client().post(
            "/resolve",
            json={
                "audio_b64": [base64.b64encode(b"fake-opus").decode()],
                "voiceprints": [
                    {"speaker_id": 7, "name": "Alice", "embedding": [1.0, 0.0]}
                ],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["match"] is None
    np.testing.assert_allclose(data["centroid"], [0.0, 1.0], atol=1e-6)


def test_resolve_riff_passthrough_skips_opus_conversion():
    """RIFF-headed audio is used as-is without opus_to_wav."""
    wav = b"RIFF" + b"\x00" * 32
    with (
        patch(
            "speaker_id.routes.encoder.extract_embedding",
            return_value=np.array([1.0, 0.0]),
        ) as embed,
        patch("speaker_id.routes.opus_to_wav") as convert,
    ):
        response = _resolve_client().post(
            "/resolve",
            json={"audio_b64": [base64.b64encode(wav).decode()], "voiceprints": []},
        )
    assert response.status_code == 200
    convert.assert_not_called()
    embed.assert_called_once_with(wav)
    assert response.json()["match"] is None


def test_resolve_no_valid_audio_400():
    """No decodable audio returns 400."""
    with patch("speaker_id.routes.encoder.extract_embedding") as embed:
        response = _resolve_client().post(
            "/resolve",
            json={"audio_b64": ["not-base64!!"], "voiceprints": []},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "no valid audio"
    embed.assert_not_called()
