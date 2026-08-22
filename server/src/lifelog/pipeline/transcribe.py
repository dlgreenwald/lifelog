import asyncio
import io
import logging
import os
import tempfile
import time
from datetime import datetime

import httpx

from lifelog.config import settings

logger = logging.getLogger("lifelog.transcribe")


async def transcribe(audio_bytes: bytes) -> dict:
    """Transcribe audio via whisper-asr-webservice with diarization.

    Returns dict with keys: text, segments (with speaker labels), language.
    """
    logger.info("Transcribing %d bytes of audio", len(audio_bytes))
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{settings.whisper_asr_url}/asr",
            params={
                "output": "json",
                "diarize": "true",
                "language": "en",
            },
            files={"audio_file": ("audio.opus", io.BytesIO(audio_bytes), "audio/opus")},
        )
        response.raise_for_status()
        result = response.json()

    duration = time.monotonic() - start
    text = result.get("text", "")
    segments = result.get("segments", [])
    speakers = {seg.get("speaker") for seg in segments if seg.get("speaker")}

    logger.info(
        "Transcription complete in %.2fs: %d chars, %d segments, %d speakers (%s)",
        duration,
        len(text),
        len(segments),
        len(speakers),
        ", ".join(sorted(speakers)) if speakers else "none",
    )

    return result


async def concatenate_opus(
    audio_list: list[bytes],
    timestamps: list[datetime],
) -> bytes:
    """Concatenate multiple Opus audio segments into one stream with silence gaps.

    Each segment is delayed by the time gap from the first segment's timestamp.
    FFmpeg handles decode, delay (silence insertion), concat, and re-encode.

    Args:
        audio_list: List of raw Opus audio bytes.
        timestamps: Parallel list of UTC datetime objects for each segment.

    Returns:
        Concatenated Opus audio as bytes.

    Raises:
        RuntimeError: If FFmpeg fails or inputs are empty.
    """
    if not audio_list:
        raise RuntimeError("No audio segments to concatenate")

    if len(audio_list) != len(timestamps):
        raise RuntimeError(
            f"audio_list length ({len(audio_list)}) != timestamps length ({len(timestamps)})"
        )

    start_time = time.monotonic()
    tmpdir = tempfile.mkdtemp(prefix="opus_concat_")

    try:
        # Write each segment to a file and compute delay
        input_args = []
        filter_parts = []

        for i, (audio_bytes, ts) in enumerate(zip(audio_list, timestamps)):
            # Compute delay in milliseconds from first timestamp
            delay_ms = int((ts - timestamps[0]).total_seconds() * 1000)

            # Write segment to temp file
            seg_path = os.path.join(tmpdir, f"seg_{i}.opus")
            with open(seg_path, "wb") as f:
                f.write(audio_bytes)

            input_args.extend(["-i", seg_path])
            # adelay filter: delay_ms|delay_ms for stereo safety
            filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

        # Concat all delayed streams
        n = len(audio_list)
        concat_inputs = "".join(f"[a{i}]" for i in range(n))
        filter_parts.append(f"{concat_inputs}concat=n={n}:v=0:a=1[out]")

        filter_complex = ";\n".join(filter_parts)

        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            *input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "libopus",
            "-b:a",
            "24000",
            "-f",
            "ogg",
            "pipe:1",
        ]

        logger.info(
            "Concatenating %d audio segments (delays: %s)",
            n,
            ", ".join(
                str(int((ts - timestamps[0]).total_seconds() * 1000)) + "ms"
                for ts in timestamps
            ),
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (exit {proc.returncode}): {stderr.decode()[:500]}"
            )

        duration_s = time.monotonic() - start_time
        logger.info(
            "Concatenation complete in %.2fs: %d bytes output",
            duration_s,
            len(stdout),
        )

        return stdout

    finally:
        # Clean up temp directory
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)


async def transcribe_batch(audio_bytes: bytes) -> dict:
    """Transcribe concatenated audio via whisper-asr with diarization.

    Same HTTP call pattern as transcribe() but for batch audio.
    Segments have timestamps relative to the start of the concatenated stream.

    Args:
        audio_bytes: Concatenated Opus audio bytes from concatenate_opus().

    Returns:
        Dict with keys: text, segments (with speaker labels), language.
    """
    logger.info("Batch transcribing %d bytes of audio", len(audio_bytes))
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            f"{settings.whisper_asr_url}/asr",
            params={
                "output": "json",
                "diarize": "true",
                "language": "en",
            },
            files={"audio_file": ("audio.opus", io.BytesIO(audio_bytes), "audio/opus")},
        )
        response.raise_for_status()
        result = response.json()

    duration = time.monotonic() - start
    text = result.get("text", "")
    segments = result.get("segments", [])
    speakers = {seg.get("speaker") for seg in segments if seg.get("speaker")}

    logger.info(
        "Batch transcription complete in %.2fs: %d chars, %d segments, %d speakers (%s)",
        duration,
        len(text),
        len(segments),
        len(speakers),
        ", ".join(sorted(speakers)) if speakers else "none",
    )

    return result
