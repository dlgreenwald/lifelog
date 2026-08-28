"""WhisperX model loading and quick/full transcription."""

from __future__ import annotations

import base64
import io
import os
import wave
from typing import Any

import numpy as np

from audio import waveform_to_numpy


def load_models() -> dict[str, Any]:
    """Load ASR, alignment, and diarization models once per worker process."""
    import whisperx
    from whisperx.diarize import DiarizationPipeline

    device = os.getenv("ASR_DEVICE", "cuda")
    compute_type = os.getenv("ASR_COMPUTE_TYPE", "float16")
    model_name = os.getenv("ASR_MODEL", "large-v3")
    cache_dir = os.getenv("MODEL_CACHE_DIR", "/root/.cache/huggingface")
    asr = whisperx.load_model(
        model_name, device=device, compute_type=compute_type, download_root=cache_dir
    )
    align_model, metadata = whisperx.load_align_model(
        language_code=os.getenv("ASR_LANGUAGE", "en"),
        device=device,
    )
    diarize = DiarizationPipeline(token=os.environ["HF_TOKEN"], device=device)
    return {
        "asr": asr,
        "align_model": align_model,
        "metadata": metadata,
        "diarize": diarize,
        "device": device,
        "compute_type": compute_type,
    }


def quick_transcribe(models: dict, audio_np: np.ndarray, sample_rate: int) -> dict:
    """Run ASR only; alignment and diarization are intentionally skipped."""
    audio_np = waveform_to_numpy(audio_np)
    result = models["asr"].transcribe(audio_np, batch_size=4)
    segments = result.get("segments", [])
    return {"segments": segments, "full_transcript": {"segments": segments}}


def group_into_speaker_segments(segments: list[dict]) -> list[dict]:
    """Merge consecutive diarized entries for the same speaker."""
    if not segments:
        return []
    groups: list[dict] = []
    for index, segment in enumerate(segments):
        speaker = segment.get("speaker") or "Unknown"
        text = str(segment.get("text", "")).strip()
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        if groups and groups[-1]["speaker"] == speaker:
            group = groups[-1]
            group["end"] = end
            group["text"] = f'{group["text"]} {text}'.strip()
            group["segment_indices"].append(index)
        else:
            groups.append({
                "speaker": speaker,
                "start": start,
                "end": end,
                "text": text,
                "segment_indices": [index],
            })
    return groups


def _extract_segment_wav(
    audio_np: np.ndarray,
    sample_rate: int,
    segments: list[dict],
    indices: list[int],
) -> str:
    """Extract selected segment ranges as base64-encoded mono PCM WAV."""
    audio_np = waveform_to_numpy(audio_np)
    if sample_rate <= 0:
        return ""
    slices = []
    for index in indices:
        if index < 0 or index >= len(segments):
            continue
        segment = segments[index]
        try:
            start = max(0, int(float(segment.get("start", 0.0)) * sample_rate))
            end = min(len(audio_np), int(float(segment.get("end", 0.0)) * sample_rate))
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        slices.append(audio_np[start:end])
    if not slices:
        return ""
    samples = np.concatenate(slices)
    pcm = np.clip(samples * 32768.0, -32768, 32767).astype("<i2").tobytes()
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return base64.b64encode(output.getvalue()).decode("ascii")


def _as_segment_dicts(segments: Any) -> list[dict]:
    if isinstance(segments, list):
        return [dict(segment) for segment in segments]
    if hasattr(segments, "iterrows"):
        return [dict(row) for _, row in segments.iterrows()]
    return []


def transcribe_audio(
    models: dict, audio_np: np.ndarray, sample_rate: int
) -> dict:
    """Run ASR, alignment, diarization, and transient speaker-audio extraction."""
    audio_np = waveform_to_numpy(audio_np)
    asr_result = models["asr"].transcribe(audio_np, batch_size=4)
    raw_segments = _as_segment_dicts(asr_result.get("segments", []))
    if not raw_segments:
        return {"segments": [], "full_transcript": {"segments": []}, "speaker_map": {}, "speaker_segments": []}

    language = asr_result.get("language", "en")
    aligned_segments = raw_segments
    align_model = models.get("align_model")
    if align_model is not None:
        import whisperx
        aligned = whisperx.align(
            raw_segments,
            align_model,
            models.get("metadata", {}),
            audio_np,
            models["device"],
            return_char_alignments=False,
        )
        aligned_segments = _as_segment_dicts(aligned.get("segments", aligned))

    diarization = models["diarize"](audio_np)
    import whisperx
    diarized = whisperx.assign_word_speakers(diarization, {"segments": aligned_segments})
    segments = _as_segment_dicts(diarized.get("segments", aligned_segments))
    groups = group_into_speaker_segments(segments)
    speaker_segments = []
    for group in groups:
        segment = {key: value for key, value in group.items() if key != "segment_indices"}
        segment["audio"] = _extract_segment_wav(
            audio_np, sample_rate, segments, group["segment_indices"]
        )
        speaker_segments.append(segment)

    speaker_map = asr_result.get("speaker_map", {})
    if not isinstance(speaker_map, dict):
        speaker_map = {}
    return {
        "segments": segments,
        "full_transcript": {"segments": segments, "language": language},
        "speaker_map": speaker_map,
        "speaker_segments": speaker_segments,
    }
