"""Mock integration tests for pipeline clients (Wyoming, diarize, speaker, LLM)."""
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- Wyoming transcribe client ---


def _make_recv_fn(response_payload: bytes):
    """Return a side_effect callable that mimics sequential recv calls."""
    len_prefix = struct.pack("!I", len(response_payload))
    call_count = [0]

    def recv_fn(n):
        call_count[0] += 1
        if call_count[0] == 1:
            return len_prefix
        return response_payload

    return recv_fn


def _make_mock_socket(response_payload: bytes):
    """Create a mock socket whose recv returns the given Wyoming response."""
    mock_sock = MagicMock()
    mock_sock.recv.side_effect = _make_recv_fn(response_payload)
    # Context manager must return the same mock so recv.side_effect is visible
    mock_sock.__enter__ = MagicMock(return_value=mock_sock)
    mock_sock.__exit__ = MagicMock(return_value=False)
    return mock_sock


def test_wyoming_client_transcribe():
    """WyomingClient sends correct protocol and parses response."""
    from lifelog.pipeline.transcribe import WyomingClient

    client = WyomingClient("localhost", 10700)

    response_payload = json.dumps({
        "text": "Hello world",
        "segments": [{"start": 0.0, "end": 1.5, "text": "Hello world"}],
    }).encode()

    mock_sock = _make_mock_socket(response_payload)

    with patch("lifelog.pipeline.transcribe.socket.socket", return_value=mock_sock):
        result = client.transcribe(b"fake-audio", sample_rate=16000)

    assert result["text"] == "Hello world"
    assert len(result["segments"]) == 1
    assert result["segments"][0]["text"] == "Hello world"


def test_wyoming_client_transcribe_empty_segments():
    """WyomingClient handles response with no segments."""
    from lifelog.pipeline.transcribe import WyomingClient

    client = WyomingClient("localhost", 10700)

    response_payload = json.dumps({
        "text": "",
        "segments": [],
    }).encode()

    mock_sock = _make_mock_socket(response_payload)

    with patch("lifelog.pipeline.transcribe.socket.socket", return_value=mock_sock):
        result = client.transcribe(b"silence")

    assert result["text"] == ""
    assert result["segments"] == []


# --- Diarize client ---


@pytest.mark.asyncio
async def test_diarize_client():
    """diarize() posts audio and returns segments from JSON response."""
    from lifelog.pipeline.diarize_client import diarize

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "segments": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.5},
        ]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("lifelog.pipeline.diarize_client.ssl.create_default_context"),              patch("lifelog.pipeline.diarize_client.httpx.AsyncClient", return_value=mock_client):
            segments = await diarize(b"fake-audio")

    assert len(segments) == 1
    assert segments[0]["speaker"] == "SPEAKER_00"
    assert segments[0]["start"] == 0.0
    assert segments[0]["end"] == 2.5


# --- Speaker client ---


@pytest.mark.asyncio
async def test_identify_speakers_client():
    """identify_speakers() sends voiceprints and returns identified segments."""
    from lifelog.pipeline.speaker_client import identify_speakers

    fake_voiceprints = [
        {"name": "Alice", "embedding": b"\x01\x02\x03"},
    ]

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "speakers": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0, "name": "Alice"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("lifelog.pipeline.speaker_client.get_all_voiceprints", new_callable=AsyncMock) as mock_vp,
        patch("lifelog.pipeline.speaker_client.ssl.create_default_context"),
        patch("lifelog.pipeline.speaker_client.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_vp.return_value = fake_voiceprints
        result = await identify_speakers(
                    segments=[{"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0}],
                    audio_bytes=b"fake-audio",
                    user_id=1,
                )

    assert len(result) == 1
    assert result[0]["name"] == "Alice"


# --- LLM summarize ---


def test_summarize():
    """summarize() formats transcript, calls OpenAI, returns parsed JSON."""
    from lifelog.pipeline.llm import summarize

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "summary": "Test summary",
        "conversation_changes": [],
        "decisions": [{"decision": "Go with plan A", "made_by": "Alice", "context": "Discussed options"}],
        "todos": [{"task": "Buy groceries", "owner": "Bob", "due": None, "priority": "medium"}],
        "calendar": [],
        "notes": ["Important note"],
    })

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    segments = [
        {"name": "Alice", "start": 0.0, "text": "Let's go with plan A"},
        {"name": "Bob", "start": 2.0, "text": "Sounds good, I'll buy groceries"},
    ]

    with patch("lifelog.pipeline.llm.client", mock_client):
        result = summarize(segments)

    assert result["summary"] == "Test summary"
    assert len(result["decisions"]) == 1
    assert result["decisions"][0]["decision"] == "Go with plan A"
    assert len(result["todos"]) == 1
    assert result["todos"][0]["task"] == "Buy groceries"

    call_args = mock_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
    user_msg = messages[1]["content"]
    assert "Alice" in user_msg
    assert "Bob" in user_msg
    assert "[0.0s]" in user_msg
