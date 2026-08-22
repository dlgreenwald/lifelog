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


MAX_INPUTS_PER_FFMPEG = 50


async def _run_ffmpeg_batch(
    audio_list: list[bytes],
    timestamps: list[datetime],
    tmpdir: str,
    batch_num: int,
) -> bytes:
    """Run a single ffmpeg concat for a batch of segments (max MAX_INPUTS_PER_FFMPEG).

    Returns concatenated opus audio bytes for this batch.
    """
    n = len(audio_list)
    input_args = []
    filter_parts = []

    for i, (audio_bytes, ts) in enumerate(zip(audio_list, timestamps)):
        delay_ms = int((ts - timestamps[0]).total_seconds() * 1000)
        seg_path = os.path.join(tmpdir, f"b{batch_num}_seg_{i}.opus")
        with open(seg_path, "wb") as f:
            f.write(audio_bytes)
        input_args.extend(["-i", seg_path])
        filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

    concat_inputs = "".join(f"[a{i}]" for i in range(n))
    filter_parts.append(f"{concat_inputs}concat=n={n}:v=0:a=1[out]")
    filter_complex = ";\n".join(filter_parts)

    filter_script_path = os.path.join(tmpdir, f"filter_b{batch_num}.txt")
    with open(filter_script_path, "w") as f:
        f.write(filter_complex)

    cmd = [
        "ffmpeg", "-y",
        *input_args,
        "-filter_complex_script", filter_script_path,
        "-map", "[out]",
        "-c:a", "libopus", "-b:a", "24000",
        "-f", "ogg", "pipe:1",
    ]

    t_cmd = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    stderr_chunks = []
    async def _read_stderr():
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk)
            text = chunk.decode(errors="replace")
            for line in text.split("\n"):
                if "size=" in line or "time=" in line:
                    logger.info("FFmpeg batch %d progress: %s", batch_num, line.strip())

    stderr_task = asyncio.create_task(_read_stderr())

    try:
        stdout = await asyncio.wait_for(proc.stdout.read(), timeout=600)
        await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        await stderr_task
        raise RuntimeError(f"FFmpeg batch {batch_num} timed out (pid={proc.pid})")

    await stderr_task
    elapsed = time.monotonic() - t_cmd
    logger.info("FFmpeg batch %d finished in %.1fs (exit=%d)", batch_num, elapsed, proc.returncode)

    if proc.returncode != 0:
        stderr_text = b"".join(stderr_chunks).decode()[:500]
        raise RuntimeError(f"FFmpeg batch {batch_num} failed (exit {proc.returncode}): {stderr_text}")

    return stdout


async def _concatopus_files(file_list: list[str], tmpdir: str) -> bytes:
    """Concat multiple opus files using ffmpeg concat demuxer (no re-encode)."""
    list_path = os.path.join(tmpdir, "concat_list.txt")
    with open(list_path, "w") as f:
        for path in file_list:
            f.write(f"file '{path}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        "-f", "ogg", "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg concat failed (exit {proc.returncode}): {stderr.decode()[:500]}")

    return stdout


async def concatenate_opus(
    audio_list: list[bytes],
    timestamps: list[datetime],
) -> bytes:
    """Concatenate multiple Opus audio segments into one stream with silence gaps.

    Splits into batches of MAX_INPUTS_PER_FFMPEG to avoid overwhelming ffmpeg,
    then concatenates batch results.

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
    n = len(audio_list)
    tmpdir = tempfile.mkdtemp(prefix="opus_concat_")

    try:
        if n <= MAX_INPUTS_PER_FFMPEG:
            # Single batch — run directly
            logger.info("Concatenating %d audio segments (single batch)", n)
            result = await _run_ffmpeg_batch(audio_list, timestamps, tmpdir, 0)
            logger.info("Concatenation complete in %.2fs: %d bytes", time.monotonic() - start_time, len(result))
            return result

        # Multiple batches
        batch_files = []
        num_batches = (n + MAX_INPUTS_PER_FFMPEG - 1) // MAX_INPUTS_PER_FFMPEG
        logger.info(
            "Concatenating %d audio segments in %d batches of %d",
            n, num_batches, MAX_INPUTS_PER_FFMPEG,
        )

        for batch_idx in range(num_batches):
            start = batch_idx * MAX_INPUTS_PER_FFMPEG
            end = min(start + MAX_INPUTS_PER_FFMPEG, n)
            batch_audio = audio_list[start:end]
            batch_ts = timestamps[start:end]

            logger.info("Processing batch %d/%d (%d segments)", batch_idx + 1, num_batches, len(batch_audio))
            batch_bytes = await _run_ffmpeg_batch(batch_audio, batch_ts, tmpdir, batch_idx)

            batch_path = os.path.join(tmpdir, f"batch_{batch_idx}.ogg")
            with open(batch_path, "wb") as f:
                f.write(batch_bytes)
            batch_files.append(batch_path)

        # Concat all batch files
        if len(batch_files) == 1:
            with open(batch_files[0], "rb") as f:
                result = f.read()
        else:
            logger.info("Concatenating %d batch files", len(batch_files))
            result = await _concatopus_files(batch_files, tmpdir)

        elapsed = time.monotonic() - start_time
        logger.info("Full concatenation complete in %.2fs: %d bytes", elapsed, len(result))
        return result

    finally:
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
