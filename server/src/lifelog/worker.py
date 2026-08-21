"""Background worker that processes utterances from the queue.

Polls for pending utterances, runs the full pipeline (transcribe → identify → summarize),
and saves the recording. Survives restarts by picking up where it left off.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime

import lifelog.database as db
from lifelog.config import settings
from lifelog.crypto import audio_crypto
from lifelog.database import (
    delete_utterance_chunks,
    get_utterance_chunks,
    is_meaningful_speech,
)
from lifelog.pipeline.llm import summarize
from lifelog.pipeline.speaker_client import identify_speakers
from lifelog.pipeline.transcribe import transcribe

logger = logging.getLogger("lifelog.worker")

# Poll interval in seconds
POLL_INTERVAL = 60.0


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
        "Utterance %d/%d complete: recording_id=%s",
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
        transcript_text = " ".join(
            seg.get("text", "").strip()
            for seg in result.get("segments", [])
        )
        logger.debug(
            "Utterance %d/%d chunk %d: %s",
            user_id,
            utterance_id,
            i,
            transcript_text or "(empty)",
        )

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

    # ── Session assignment ──────────────────────────────────────────

    full_transcript = {"segments": all_transcript_segments}

    # Get the utterance's timestamp from the queue
    queue_entry = await db.get_utterance_queue_entry(user_id, utterance_id)
    utterance_time = (
        queue_entry["created_at"]
        if queue_entry
        else datetime.now(UTC).replace(tzinfo=None)
    )

    # Determine if this utterance has meaningful speech
    meaningful = is_meaningful_speech(all_named_segments)

    # Get or create session
    active_session = await db.get_active_session(user_id)
    session_id: int | None = None

    if active_session:
        # Check gap from last meaningful utterance in the session
        last_meaningful_time = await db.get_last_meaningful_utterance_time(
            active_session["id"]
        )
        ref_time = last_meaningful_time or active_session["started_at"]
        gap_minutes = (
            utterance_time - ref_time.replace(tzinfo=None)
        ).total_seconds() / 60

        if gap_minutes <= settings.session_gap_minutes:
            # Within window — append to existing session
            session_id = active_session["id"]
        else:
            # Gap too large — end current session, create new one
            await db.end_session(active_session["id"])
            session_id = await db.create_session(user_id, utterance_time)
    else:
        # No active session — create one
        session_id = await db.create_session(user_id, utterance_time)

    # Store utterance in session
    audio_filename = audio_filenames[0] if audio_filenames else ""
    await db.append_session_utterance(
        session_id,
        utterance_id,
        audio_filename,
        full_transcript,
        all_named_segments,
        meaningful,
    )

    await complete_utterance(user_id, utterance_id, None)

    total_duration = time.monotonic() - start
    logger.info(
        "Utterance %d/%d assigned to session %d in %.2fs: %d segments, meaningful=%s",
        user_id,
        utterance_id,
        session_id,
        total_duration,
        len(all_named_segments),
        meaningful,
    )


async def worker_loop():
    """Main worker loop — polls for pending utterances and processes them."""
    logger.info("Worker started, polling every %.0fs", POLL_INTERVAL)

    while True:
        try:
            pending = await get_pending_utterances()
            logger.debug("Poll: %d pending utterance(s)", len(pending))

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


# ── Hourly reprocessing ────────────────────────────────────────────


async def _reprocess_session(session: dict):
    """Run LLM summarization on a session's meaningful utterances and save recording."""
    session_id = session["id"]
    user_id = session["user_id"]

    utterances = await db.get_session_meaningful_utterances(session_id)
    if not utterances:
        logger.warning("Session %d has no meaningful utterances, skipping", session_id)
        return

    # Concatenate transcripts with cumulative timestamps
    cumulative_offset = 0.0
    all_named_segments = []
    for utt in utterances:
        named = utt["named_segments"]
        if isinstance(named, str):
            import json
            named = json.loads(named)
        # Offset timestamps by cumulative duration from prior utterances
        for seg in named:
            seg["start"] = seg.get("start", 0) + cumulative_offset
            seg["end"] = seg.get("end", 0) + cumulative_offset
        all_named_segments.extend(named)

        # Calculate duration of this utterance for offset
        if named:
            max_end = max(seg.get("end", 0) for seg in named)
            cumulative_offset = max_end

    # Build combined transcript
    full_transcript = {"segments": []}
    for utt in utterances:
        transcript = utt["transcript"]
        if isinstance(transcript, str):
            import json
            transcript = json.loads(transcript)
        full_transcript["segments"].extend(transcript.get("segments", []))

    # Get audio filenames for this session
    audio_files = await db.get_recording_audio_filenames(session_id)
    first_audio = audio_files[0] if audio_files else ""

    # LLM summarization
    result = summarize(all_named_segments)

    # Save (or update) recording
    await db.save_session_recording(
        user_id, session_id, full_transcript,
        all_named_segments, result, first_audio,
    )

    # Mark session as processed
    await db.mark_session_processed(session_id)
    logger.info(
        "Session %d reprocessed: %d segments, %d todos",
        session_id,
        len(all_named_segments),
        len(result.get("todos", [])),
    )


async def hourly_reprocess_loop():
    """Run every hour: process ended sessions that need LLM summarization."""
    interval = settings.hourly_reprocess_interval_minutes * 60
    logger.info(
        "Hourly reprocess loop started (interval=%ds)",
        settings.hourly_reprocess_interval_minutes * 60,
    )

    while True:
        await asyncio.sleep(interval)

        try:
            sessions = await db.get_sessions_for_reprocessing()
            logger.info("Hourly reprocess: %d session(s) to process", len(sessions))
            for session in sessions:
                try:
                    await _reprocess_session(session)
                except Exception:
                    logger.exception(
                        "Error reprocessing session %d", session["id"]
                    )
        except Exception:
            logger.exception("Hourly reprocess loop error")


# ── Daily reprocessing ─────────────────────────────────────────────


async def _daily_reprocess_user(user_id: int):
    """Join adjacent sessions from previous day and re-summarize."""
    from datetime import timedelta

    now = datetime.now(UTC)
    day_start = (now - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    day_end = day_start + timedelta(days=1)

    sessions = await db.get_sessions_by_date_range(user_id, day_start, day_end)
    if len(sessions) < 2:
        # Nothing to join; still re-summarize the single session if it exists
        if sessions:
            await _reprocess_session(sessions[0])
        return

    # Sort by started_at
    sessions.sort(key=lambda s: s["started_at"])

    # Join adjacent sessions where gap < session_gap_minutes
    merged = [sessions[0]]
    for s in sessions[1:]:
        prev = merged[-1]
        gap = (s["started_at"] - prev["ended_at"]).total_seconds() / 60
        if gap < settings.session_gap_minutes:
            # Merge into previous
            await db.join_sessions([prev["id"], s["id"]], prev["id"])
            prev["ended_at"] = s["ended_at"]
        else:
            merged.append(s)

    # Re-summarize each remaining session with day context
    earlier_summaries = []
    for session in merged:
        # Include preamble of earlier sessions if available
        if earlier_summaries:
            preamble = "Earlier today, the following conversations occurred:\n"
            for i, summary_text in enumerate(earlier_summaries):
                preamble += f"{i + 1}. {summary_text}\n"
            preamble += "\nCurrent conversation to analyze:\n"
            # TODO: could inject preamble into LLM prompt
            # For now, just re-summarize normally

        utterances = await db.get_session_meaningful_utterances(session["id"])
        if not utterances:
            continue

        cumulative_offset = 0.0
        all_named_segments = []
        for utt in utterances:
            named = utt["named_segments"]
            if isinstance(named, str):
                import json
                named = json.loads(named)
            for seg in named:
                seg["start"] = seg.get("start", 0) + cumulative_offset
                seg["end"] = seg.get("end", 0) + cumulative_offset
            all_named_segments.extend(named)
            if named:
                max_end = max(seg.get("end", 0) for seg in named)
                cumulative_offset = max_end

        result = summarize(all_named_segments)

        audio_files = await db.get_recording_audio_filenames(session["id"])
        first_audio = audio_files[0] if audio_files else ""

        full_transcript = {"segments": []}
        for utt in utterances:
            transcript = utt["transcript"]
            if isinstance(transcript, str):
                import json
                transcript = json.loads(transcript)
            full_transcript["segments"].extend(transcript.get("segments", []))

        await db.save_session_recording(
            user_id, session["id"], full_transcript,
            all_named_segments, result, first_audio,
        )

        earlier_summaries.append(result.get("summary", ""))

    logger.info(
        "Daily reprocess for user %d: %d sessions (%d merged)",
        user_id,
        len(sessions),
        len(sessions) - len(merged),
    )


async def daily_reprocess_loop():
    """Run once daily at configured hour: join adjacent sessions and re-summarize."""
    from datetime import timedelta

    logger.info("Daily reprocess loop started (hour=%d UTC)", settings.daily_reprocess_hour)

    while True:
        # Calculate seconds until next daily run
        now = datetime.now(UTC)
        target = now.replace(
            hour=settings.daily_reprocess_hour, minute=0, second=0, microsecond=0
        )
        if target <= now:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        logger.info("Daily reprocess: sleeping %.0fs until %s", wait_seconds, target)
        await asyncio.sleep(wait_seconds)

        try:
            # Find all users with sessions
            sessions = await db.get_sessions_for_reprocessing()
            user_ids = list({s["user_id"] for s in sessions})
            logger.info("Daily reprocess: %d user(s) to process", len(user_ids))
            for uid in user_ids:
                try:
                    await _daily_reprocess_user(uid)
                except Exception:
                    logger.exception("Error in daily reprocess for user %d", uid)
        except Exception:
            logger.exception("Daily reprocess loop error")
