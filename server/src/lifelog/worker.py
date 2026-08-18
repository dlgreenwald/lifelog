"""Background worker that processes utterances from the queue.

Polls for pending utterances, runs the full pipeline (transcribe → identify → summarize),
and saves the recording. Survives restarts by picking up where it left off.
"""

import asyncio
import logging
import time

from lifelog.config import settings
from lifelog.crypto import audio_crypto
import lifelog.database as db
from lifelog.database import (
    delete_utterance_chunks,
    get_utterance_chunks,
    get_user_by_api_key,
    save_recording,
)
from lifelog.pipeline.llm import summarize
from lifelog.pipeline.speaker_client import identify_speakers
from lifelog.pipeline.transcribe import transcribe

logger = logging.getLogger("lifelog.worker")

# Poll interval in seconds
POLL_INTERVAL = 2.0


async def claim_utterance(user_id: int, utterance_id: int) -> bool:
    """Try to claim an utterance for processing. Returns True if claimed."""
    async with db.pool.acquire() as conn:
        result = await conn.execute(
            """INSERT INTO utterance_queue (user_id, utterance_id, status, started_at)
               VALUES ($1, $2, 'processing', NOW())
               ON CONFLICT (user_id, utterance_id) DO UPDATE
               SET status = 'processing', started_at = NOW()
               WHERE utterance_queue.status = 'pending'""",
            user_id,
            utterance_id,
        )
        # ON CONFLICT returns INSERT 0 1 if no pending row existed
        return result.split()[-1] != "0"


async def complete_utterance(user_id: int, utterance_id: int, recording_id: int):
    """Mark an utterance as done."""
    async with db.pool.acquire() as conn:
        await conn.execute(
            """UPDATE utterance_queue
               SET status = 'done', completed_at = NOW()
               WHERE user_id = $1 AND utterance_id = $2""",
            user_id,
            utterance_id,
        )
    logger.info(
        "Utterance %d/%d complete: recording_id=%d",
        user_id,
        utterance_id,
        recording_id,
    )


async def fail_utterance(user_id: int, utterance_id: int, error: str):
    """Mark an utterance as failed."""
    async with db.pool.acquire() as conn:
        await conn.execute(
            """UPDATE utterance_queue
               SET status = 'failed', error = $3, completed_at = NOW()
               WHERE user_id = $1 AND utterance_id = $2""",
            user_id,
            utterance_id,
            error,
        )
    logger.error("Utterance %d/%d failed: %s", user_id, utterance_id, error)


async def get_pending_utterances() -> list[dict]:
    """Find utterances ready to process: queue entry with status 'pending'."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id, utterance_id
               FROM utterance_queue
               WHERE status = 'pending'
               ORDER BY user_id, utterance_id"""
        )
        return [dict(row) for row in rows]


async def get_user_secret(user_id: int) -> str | None:
    """Get user's encryption_secret for audio decryption."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT encryption_secret FROM users WHERE id = $1",
            user_id,
        )
        return row["encryption_secret"] if row else None


async def process_utterance(user_id: int, utterance_id: int):
    """Process a single utterance through the full pipeline."""
    start = time.monotonic()
    logger.info("Processing utterance %d/%d", user_id, utterance_id)

    # Retrieve chunks
    chunks = await get_utterance_chunks(user_id, utterance_id)
    if not chunks:
        logger.warning("No chunks found for utterance %d/%d", user_id, utterance_id)
        await fail_utterance(user_id, utterance_id, "no chunks found")
        return

    logger.info("Utterance %d/%d: %d chunks", user_id, utterance_id, len(chunks))

    encryption_secret = await get_user_secret(user_id)
    if not encryption_secret:
        await fail_utterance(user_id, utterance_id, "user not found")
        return

    all_named_segments = []
    all_transcript_segments = []
    audio_filenames = []

    for i, chunk in enumerate(chunks):
        chunk_start = time.monotonic()
        chunk_audio = chunk["audio_bytes"]

        # Encrypt
        chunk_filename = audio_crypto.encrypt_audio(
            chunk_audio, user_id, encryption_secret
        )
        audio_filenames.append(chunk_filename)

        # Transcribe + diarize
        result = await transcribe(chunk_audio)

        # Extract diarization for speaker matching
        diarization_segments = [
            {
                "speaker": seg.get("speaker", "SPEAKER_00"),
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
            }
            for seg in result.get("segments", [])
            if seg.get("speaker")
        ]

        # Match speakers to voiceprints
        speakers = await identify_speakers(diarization_segments, chunk_audio, user_id)

        # Build named segments
        speaker_map = {s.get("speaker", ""): s.get("name", "Unknown") for s in speakers}
        named_segments = []
        for j, seg in enumerate(result.get("segments", [])):
            speaker_id = seg.get("speaker", "SPEAKER_00")
            named_segments.append(
                {
                    "id": j,
                    "name": speaker_map.get(speaker_id, speaker_id),
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", "").strip(),
                }
            )

        # Offset timestamps by chunk position
        chunk_offset = chunk["chunk_index"] * 5.0
        for seg in named_segments:
            seg["start"] += chunk_offset
            seg["end"] += chunk_offset

        all_named_segments.extend(named_segments)
        all_transcript_segments.extend(result.get("segments", []))

        chunk_duration = time.monotonic() - chunk_start
        logger.info(
            "Chunk %d/%d done in %.2fs: %d segments",
            i + 1,
            len(chunks),
            chunk_duration,
            len(named_segments),
        )

    # Clean up chunks from DB
    await delete_utterance_chunks(user_id, utterance_id)

    # Summarize
    full_transcript = {"segments": all_transcript_segments}
    result = summarize(all_named_segments)

    # Save recording
    recording_id = await save_recording(
        user_id, full_transcript, all_named_segments, result, audio_filenames[0]
    )

    # Update recording with utterance_id
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE recordings SET utterance_id = $1 WHERE id = $2",
            utterance_id,
            recording_id,
        )

    await complete_utterance(user_id, utterance_id, recording_id)

    total_duration = time.monotonic() - start
    logger.info(
        "Utterance %d/%d fully processed in %.2fs: recording_id=%d, %d segments, %d todos",
        user_id,
        utterance_id,
        total_duration,
        recording_id,
        len(all_named_segments),
        len(result.get("todos", [])),
    )


async def worker_loop():
    """Main worker loop — polls for pending utterances and processes them."""
    logger.info("Worker started, polling every %.1fs", POLL_INTERVAL)

    while True:
        try:
            pending = await get_pending_utterances()
            logger.info("Poll: %d pending utterance(s)", len(pending))

            for utterance in pending:
                user_id = utterance["user_id"]
                utterance_id = utterance["utterance_id"]

                # Try to claim
                if not await claim_utterance(user_id, utterance_id):
                    continue

                try:
                    await process_utterance(user_id, utterance_id)
                except Exception as e:
                    logger.exception(
                        "Error processing utterance %d/%d", user_id, utterance_id
                    )
                    await fail_utterance(user_id, utterance_id, str(e))

        except Exception:
            logger.exception("Worker poll error")

        await asyncio.sleep(POLL_INTERVAL)
