"""Mock integration tests for pipeline clients (whisper-asr, speaker, LLM)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- Whisper ASR transcribe client ---


@pytest.mark.asyncio
async def test_transcribe_client():
    """transcribe() posts audio and returns JSON with segments and speaker labels."""
    from lifelog.pipeline.transcribe import transcribe

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "text": "Hello world",
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "Hello world", "speaker": "SPEAKER_00"},
        ],
        "language": "en",
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("lifelog.pipeline.transcribe.httpx.AsyncClient", return_value=mock_client):
        result = await transcribe(b"fake-audio")

    assert result["text"] == "Hello world"
    assert len(result["segments"]) == 1
    assert result["segments"][0]["speaker"] == "SPEAKER_00"
    assert result["segments"][0]["text"] == "Hello world"


@pytest.mark.asyncio
async def test_transcribe_client_empty():
    """transcribe() handles empty response."""
    from lifelog.pipeline.transcribe import transcribe

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "", "segments": [], "language": "en"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("lifelog.pipeline.transcribe.httpx.AsyncClient", return_value=mock_client):
        result = await transcribe(b"silence")

    assert result["text"] == ""
    assert result["segments"] == []


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
        "category": "work",
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

    assert result["category"] == "work"
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


# --- Batch transcription (concatenate_opus + transcribe_batch) ---


@pytest.mark.asyncio
async def test_concatenate_opus_empty():
    """concatenate_opus() raises RuntimeError on empty input."""
    from lifelog.pipeline.transcribe import concatenate_opus

    with pytest.raises(RuntimeError, match="No audio segments"):
        await concatenate_opus([], [])


@pytest.mark.asyncio
async def test_concatenate_opus_mismatched_lengths():
    """concatenate_opus() raises RuntimeError when audio_list and timestamps differ."""
    from datetime import datetime
    from lifelog.pipeline.transcribe import concatenate_opus

    with pytest.raises(RuntimeError, match="audio_list length"):
        await concatenate_opus([b"audio1"], [datetime(2025, 1, 1), datetime(2025, 1, 2)])


@pytest.mark.asyncio
async def test_concatenate_opus_calls_ffmpeg():
    """concatenate_opus() writes segments to temp files, runs FFmpeg, returns output."""
    from datetime import datetime
    from lifelog.pipeline.transcribe import concatenate_opus

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate.return_value = (b"concatenated-opus-bytes", b"")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await concatenate_opus(
            audio_list=[b"seg0", b"seg1"],
            timestamps=[
                datetime(2025, 1, 1, 10, 0, 0),
                datetime(2025, 1, 1, 10, 0, 5),
            ],
        )

    assert result == b"concatenated-opus-bytes"

    # Verify FFmpeg was called with correct args
    call_args = mock_exec.call_args
    cmd = call_args[0]
    assert cmd[0] == "ffmpeg"
    assert "-filter_complex" in cmd
    # adelay for second segment: 5000ms
    assert any("adelay=5000|5000" in str(arg) for arg in cmd)


@pytest.mark.asyncio
async def test_concatenate_opus_ffmpeg_failure():
    """concatenate_opus() raises RuntimeError when FFmpeg fails."""
    from datetime import datetime
    from lifelog.pipeline.transcribe import concatenate_opus

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate.return_value = (b"", b"Error: invalid codec")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="FFmpeg failed"):
            await concatenate_opus(
                audio_list=[b"seg0"],
                timestamps=[datetime(2025, 1, 1, 10, 0, 0)],
            )


@pytest.mark.asyncio
async def test_transcribe_batch_client():
    """transcribe_batch() posts concatenated audio and returns JSON."""
    from lifelog.pipeline.transcribe import transcribe_batch

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "text": "Hello from batch",
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "Hello from batch", "speaker": "SPEAKER_00"},
            {"start": 5.0, "end": 8.0, "text": "Response", "speaker": "SPEAKER_01"},
        ],
        "language": "en",
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("lifelog.pipeline.transcribe.httpx.AsyncClient", return_value=mock_client):
        result = await transcribe_batch(b"concatenated-opus-audio")

    assert result["text"] == "Hello from batch"
    assert len(result["segments"]) == 2
    assert result["segments"][0]["speaker"] == "SPEAKER_00"
    assert result["segments"][1]["speaker"] == "SPEAKER_01"


# --- Segment-to-utterance mapping ---


def test_segment_to_utterance_mapping_basic():
    """Batch segments are correctly mapped to utterances by timestamp overlap."""
    # Simulate 2 utterances, 2s each, with 3s gap
    utterances = [
        {"utterance_id": 1, "created_at": 0.0},
        {"utterance_id": 2, "created_at": 5.0},
    ]

    batch_segments = [
        {"start": 0.5, "end": 1.5, "text": "Hi", "speaker": "SPEAKER_00"},
        {"start": 5.5, "end": 6.5, "text": "Hello", "speaker": "SPEAKER_01"},
    ]

    # Compute offsets
    utterance_offsets = [0.0, 3.0]  # After compression: gap is 3s (5-2)
    # Actually with the new scheme, offsets are based on gap between timestamps

    # Map segments
    utterance_segments = {1: [], 2: []}
    for seg in batch_segments:
        seg_start = seg["start"]
        for i, utt in enumerate(utterances):
            offset = utterance_offsets[i]
            duration = 3.0  # gap estimate
            if seg_start >= offset and seg_start < offset + duration:
                utterance_segments[utt["utterance_id"]].append(seg)
                break

    assert len(utterance_segments[1]) == 1
    assert utterance_segments[1][0]["text"] == "Hi"
    assert len(utterance_segments[2]) == 1
    assert utterance_segments[2][0]["text"] == "Hello"


def test_segment_to_utterance_mapping_edge_case():
    """Segment at exact boundary falls into correct utterance."""
    utterances = [
        {"utterance_id": 1, "created_at": 0.0},
        {"utterance_id": 2, "created_at": 5.0},
    ]

    batch_segments = [
        {"start": 3.0, "end": 4.0, "text": "Boundary", "speaker": "SPEAKER_00"},
    ]

    utterance_offsets = [0.0, 3.0]

    utterance_segments = {1: [], 2: []}
    for seg in batch_segments:
        seg_start = seg["start"]
        for i, utt in enumerate(utterances):
            offset = utterance_offsets[i]
            duration = 3.0
            if seg_start >= offset and seg_start < offset + duration:
                utterance_segments[utt["utterance_id"]].append(seg)
                break

    # 3.0 >= 3.0 and 3.0 < 6.0 → belongs to utterance 2
    assert len(utterance_segments[1]) == 0
    assert len(utterance_segments[2]) == 1
    assert utterance_segments[2][0]["text"] == "Boundary"


def test_segment_to_utterance_mapping_no_match():
    """Segment beyond all utterance ranges falls to last utterance."""
    utterances = [
        {"utterance_id": 1, "created_at": 0.0},
    ]

    batch_segments = [
        {"start": 100.0, "end": 101.0, "text": "Orphan", "speaker": "SPEAKER_00"},
    ]

    utterance_offsets = [0.0]

    utterance_segments = {1: []}
    for seg in batch_segments:
        seg_start = seg["start"]
        assigned = False
        for i, utt in enumerate(utterances):
            offset = utterance_offsets[i]
            duration = 2.0
            if seg_start >= offset and seg_start < offset + duration:
                utterance_segments[utt["utterance_id"]].append(seg)
                assigned = True
                break
        if not assigned:
            # Edge case fallback
            uid = utterances[-1]["utterance_id"]
            utterance_segments[uid].append(seg)

    assert len(utterance_segments[1]) == 1
    assert utterance_segments[1][0]["text"] == "Orphan"
