"""Mock integration tests for speaker and LLM pipeline clients."""

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_identify_speakers_client():
    """identify_speakers() sends voiceprints and base64 audio."""
    from lifelog.pipeline.speaker_client import identify_speakers

    fake_voiceprints = [{"name": "Alice", "embedding": b"\x01\x02\x03"}]
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "speakers": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0, "name": "Alice"}
        ]
    }
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "lifelog.pipeline.speaker_client.get_all_voiceprints",
            new_callable=AsyncMock,
        ) as mock_vp,
        patch(
            "lifelog.pipeline.speaker_client.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        mock_vp.return_value = fake_voiceprints
        result = await identify_speakers(
            segments=[{"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0}],
            audio_bytes=b"fake-audio",
            user_id=1,
        )

    assert len(result) == 1
    request_json = mock_client.post.call_args.kwargs["json"]
    assert base64.b64decode(request_json["audio_bytes"]) == b"fake-audio"
    assert result[0]["name"] == "Alice"


def test_summarize():
    """summarize() formats transcript, calls OpenAI, returns parsed JSON."""
    from lifelog.pipeline.llm import summarize

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(
        {
            "category": "work",
            "summary": "Test summary",
            "conversation_changes": [],
            "decisions": [
                {
                    "decision": "Go with plan A",
                    "made_by": "Alice",
                    "context": "Discussed options",
                }
            ],
            "todos": [
                {
                    "task": "Buy groceries",
                    "owner": "Bob",
                    "due": None,
                    "priority": "medium",
                }
            ],
            "calendar": [],
            "notes": ["Important note"],
        }
    )
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

    assert result["category"] == "work"
    assert result["summary"] == "Test summary"
    assert len(result["decisions"]) == 1
    assert result["decisions"][0]["decision"] == "Go with plan A"
    assert len(result["todos"]) == 1
    assert result["todos"][0]["task"] == "Buy groceries"
    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    user_msg = messages[1]["content"]
    assert "Alice" in user_msg


def test_summarize_with_context():
    """summarize() includes llm_context in the prompt sent to the LLM."""
    from lifelog.pipeline.llm import summarize

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(
        {
            "category": "work",
            "summary": "Test summary",
            "conversation_changes": [],
            "decisions": [],
            "todos": [],
            "calendar": [],
            "notes": [],
        }
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    segments = [
        {"name": "Alice", "start": 0.0, "text": "Let's discuss the project."},
    ]
    llm_context = "I work as a developer and my colleague is Alice."

    with patch("lifelog.pipeline.llm.client", mock_client):
        summarize(segments, llm_context=llm_context)

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    user_msg = messages[1]["content"]
    assert "USER CONTEXT:" in user_msg
    assert llm_context in user_msg
    assert "Alice" in user_msg
    assert "[0.0s]" in user_msg
