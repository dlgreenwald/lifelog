"""Background worker that processes utterances from the queue.

Polls for pending utterances, runs the full pipeline (transcribe → identify → summarize),
and saves the recording. Survives restarts by picking up where it left off.
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

import lifelog.database as db
from lifelog.config import settings
from lifelog.crypto import audio_crypto
from lifelog.database import (
    delete_utterance_chunks,
    get_utterance_chunks,
)
from lifelog.pipeline.llm import summarize

logger = logging.getLogger("lifelog.worker")

# Poll interval in seconds
POLL_INTERVAL = 60.0

# Live transcription window state: session_id -> last window end time
_live_window_state: dict[int, datetime] = {}


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


async def get_user_secret(user_id: int) -> dict | None:
    """Get user's encryption_secret and key_salt for audio encryption."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT encryption_secret, key_salt FROM users WHERE id = $1",
            user_id,
        )
        return dict(row) if row else None


async def process_utterance(user_id: int, utterance_id: int):
    """Process a single utterance: encrypt audio and assign to session.

    Transcription is deferred to batch processing at session end.
    """
    start = time.monotonic()
    logger.info("Processing utterance %d/%d", user_id, utterance_id)

    # Retrieve chunks
    chunks = await get_utterance_chunks(user_id, utterance_id)
    if not chunks:
        logger.warning("No chunks found for utterance %d/%d", user_id, utterance_id)
        await fail_utterance(user_id, utterance_id, "no chunks found")
        return

    logger.info("Utterance %d/%d: %d chunks", user_id, utterance_id, len(chunks))

    user_secrets = await get_user_secret(user_id)
    if not user_secrets:
        await fail_utterance(user_id, utterance_id, "user not found")
        return

    encryption_secret = user_secrets["encryption_secret"]
    key_salt = bytes(user_secrets["key_salt"])

    # Encrypt audio chunks for long-term storage
    audio_filenames = []
    for i, chunk in enumerate(chunks):
        chunk_start = time.monotonic()
        chunk_audio = chunk["audio_bytes"]

        # Encrypt
        chunk_filename = audio_crypto.encrypt_audio(
            chunk_audio, encryption_secret, key_salt
        )
        audio_filenames.append(chunk_filename)

        chunk_duration = time.monotonic() - chunk_start
        logger.debug(
            "Utterance %d/%d chunk %d: encrypted in %.2fs",
            user_id,
            utterance_id,
            i,
            chunk_duration,
        )

    # Clean up chunks from DB
    await delete_utterance_chunks(user_id, utterance_id)

    # ── Session assignment ──────────────────────────────────────────

    # Get the utterance's timestamp from the queue
    queue_entry = await db.get_utterance_queue_entry(user_id, utterance_id)
    utterance_time = (
        queue_entry["created_at"]
        if queue_entry
        else datetime.now(UTC).replace(tzinfo=None)
    )

    # Get or create session
    active_session = await db.get_active_session(user_id)
    session_id: int | None = None

    if active_session:
        # Check gap from last utterance in the session
        last_utterance_time = await db.get_last_utterance_time(
            active_session["id"]
        )
        ref_time = last_utterance_time or active_session["started_at"]
        gap_minutes = (
            utterance_time - ref_time.replace(tzinfo=None)
        ).total_seconds() / 60

        if gap_minutes <= settings.session_gap_minutes:
            # Within window — append to existing session
            session_id = active_session["id"]
        else:
            # Gap too large — end current session and reprocess immediately
            await db.end_session(active_session["id"])
            logger.info(
                "Session %d ended (gap %.1f min > %d min), reprocessing",
                active_session["id"],
                gap_minutes,
                settings.session_gap_minutes,
            )
            try:
                await _reprocess_session(active_session)
            except Exception:
                logger.exception("Error reprocessing session %d on end", active_session["id"])
            session_id = await db.create_session(user_id, utterance_time)
    else:
        # No active session — create one
        session_id = await db.create_session(user_id, utterance_time)

    # Store utterance in session with empty transcript/named_segments.
    # Batch transcription at session end will populate these.
    audio_filename = audio_filenames[0] if audio_filenames else ""
    await db.append_session_utterance(
        session_id,
        utterance_id,
        audio_filename,
        {},  # transcript — empty until batch transcription
        [],  # named_segments — empty until batch transcription
        utterance_timestamp=utterance_time,
    )

    await complete_utterance(user_id, utterance_id, None)

    total_duration = time.monotonic() - start
    logger.info(
        "Utterance %d/%d assigned to session %d in %.2fs (deferred transcription)",
        user_id,
        utterance_id,
        session_id,
        total_duration,
    )


async def worker_loop():
    """Main worker loop — polls for pending utterances and processes them.

    Also checks for idle active sessions that need ending (no utterances
    for longer than session_gap_minutes).
    """
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

            # Live transcription sliding window for active sessions
            try:
                active_sessions = await db.get_active_sessions_with_utterances()
                for session in active_sessions:
                    sid = session["id"]
                    last_time = await db.get_last_utterance_time(sid)
                    if not last_time:
                        continue
                    window_end = last_time.replace(tzinfo=None)
                    window_seconds = settings.live_transcribe_window_seconds
                    overlap_seconds = settings.live_transcribe_overlap_seconds
                    window_start_raw = window_end - timedelta(seconds=window_seconds)
                    window_start_overlap = window_start_raw - timedelta(seconds=overlap_seconds)

                    # Advance window every (window - overlap) seconds
                    advance = window_seconds - overlap_seconds
                    last_window_end = _live_window_state.get(sid)
                    if last_window_end is None or (window_end - last_window_end).total_seconds() >= advance:
                        try:
                            logger.info(
                                "Live window transcribe session %d [%s, %s]",
                                sid, window_start_overlap, window_end,
                            )
                            await transcribe_window(session, window_start_overlap, window_end)
                            _live_window_state[sid] = window_end
                        except Exception:
                            logger.exception("Error in live window transcribe for session %d", sid)

                # Clean up state for sessions no longer active
                active_ids = {s["id"] for s in active_sessions}
                stale_ids = [sid for sid in _live_window_state if sid not in active_ids]
                for sid in stale_ids:
                    del _live_window_state[sid]
            except Exception:
                logger.exception("Error in live transcription window")

            # End idle active sessions (no activity for > session_gap_minutes)
            try:
                idle_sessions = await db.get_idle_active_sessions(
                    settings.session_gap_minutes
                )
                for session in idle_sessions:
                    logger.info(
                        "Ending idle session %d (user %d, started %s)",
                        session["id"],
                        session["user_id"],
                        session["started_at"],
                    )
                    await db.end_session(session["id"])
                    try:
                        await _reprocess_session(session)
                    except Exception:
                        logger.exception(
                            "Error reprocessing idle session %d", session["id"]
                        )
            except Exception:
                logger.exception("Error checking idle sessions")

        except Exception:
            logger.exception("Worker poll error")

        await asyncio.sleep(POLL_INTERVAL)


# ── Live transcription (sliding window) ────────────────────────────


async def transcribe_window(
    session: dict, window_start: datetime, window_end: datetime
) -> dict:
    """Transcribe a time window of session audio, map segments to utterances.

    Fetches utterances in [window_start, window_end], decrypts audio,
    concatenates with silence gaps, batch-transcribes, maps segments back
    to individual utterances, identifies speakers, and updates DB.

    Returns dict with all_named_segments, full_transcript, speaker_map.
    """
    from lifelog.pipeline.speaker_client import identify_speakers
    from lifelog.pipeline.transcribe import concatenate_opus, transcribe_batch

    session_id = session["id"]
    user_id = session["user_id"]

    utterances = await db.get_session_utterances_in_range(
        session_id, window_start, window_end
    )
    if not utterances:
        logger.warning(
            "Session %d: no utterances in window [%s, %s], skipping",
            session_id, window_start, window_end,
        )
        return {"all_named_segments": [], "full_transcript": {"segments": []}, "speaker_map": {}}

    # Get user's encryption secret
    user_secrets = await get_user_secret(user_id)
    if not user_secrets:
        logger.error("Session %d: user %d has no encryption secret", session_id, user_id)
        return {"all_named_segments": [], "full_transcript": {"segments": []}, "speaker_map": {}}

    encryption_secret = user_secrets["encryption_secret"]
    key_salt = bytes(user_secrets["key_salt"])

    # Decrypt audio for each utterance and collect timestamps
    audio_list: list[bytes] = []
    timestamps = []
    for utt in utterances:
        audio_filename = utt["audio_filename"]
        if not audio_filename:
            logger.warning("Session %d: utterance %d has no audio, skipping",
                          session_id, utt["utterance_id"])
            continue
        decrypted = audio_crypto.decrypt_audio(audio_filename, encryption_secret, key_salt)
        audio_list.append(decrypted)
        timestamps.append(utt["created_at"])

    if not audio_list:
        logger.warning("Session %d: no audio to transcribe, skipping", session_id)
        return {"all_named_segments": [], "full_transcript": {"segments": []}, "speaker_map": {}}

    # Concatenate all audio into one stream with silence gaps
    logger.info("Session %d: concatenating %d audio segments", session_id, len(audio_list))
    concatenated = await concatenate_opus(audio_list, timestamps)

    # Batch transcribe with diarization
    logger.info("Session %d: batch transcribing %d bytes", session_id, len(concatenated))
    batch_result = await transcribe_batch(concatenated)
    batch_segments = batch_result.get("segments", [])
    logger.info(
        "Session %d: batch transcription complete: %d segments",
        session_id,
        len(batch_segments),
    )

    # Map batch segments back to individual utterances by timestamp overlap.
    # Each utterance's offset in the concatenated stream is the sum of durations
    # of all prior utterances (duration = gap to next created_at, or 2s default).
    utterance_offsets = []
    cumulative_offset = 0.0
    for idx, utt in enumerate(utterances):
        utterance_offsets.append(cumulative_offset)
        if idx + 1 < len(utterances):
            gap = (utterances[idx + 1]["created_at"] - utt["created_at"]).total_seconds()
        else:
            gap = 2.0  # Conservative estimate
        cumulative_offset += gap

    # Assign each batch segment to an utterance by timestamp overlap
    all_named_segments = []
    full_transcript = {"segments": []}
    utterance_segments: dict[int, list] = {}
    utterance_transcripts: dict[int, list] = {}

    for utt in utterances:
        utterance_segments[utt["utterance_id"]] = []
        utterance_transcripts[utt["utterance_id"]] = []

    for seg in batch_segments:
        seg_start = seg.get("start", 0)
        assigned = False
        for i, utt in enumerate(utterances):
            utt_offset = utterance_offsets[i]
            if i + 1 < len(utterances):
                utt_duration = (utterances[i + 1]["created_at"] - utt["created_at"]).total_seconds()
            else:
                utt_duration = 2.0

            if seg_start >= utt_offset and seg_start < utt_offset + utt_duration:
                uid = utt["utterance_id"]
                named_seg = {
                    "id": len(utterance_segments[uid]),
                    "name": seg.get("speaker", "SPEAKER_00"),
                    "start": seg.get("start", 0) - utt_offset,
                    "end": seg.get("end", 0) - utt_offset,
                    "text": seg.get("text", "").strip(),
                }
                utterance_segments[uid].append(named_seg)
                utterance_transcripts[uid].append(seg)
                all_named_segments.append(named_seg)
                full_transcript["segments"].append(seg)
                assigned = True
                break

        if not assigned and utterances:
            last_utt = utterances[-1]
            uid = last_utt["utterance_id"]
            named_seg = {
                "id": len(utterance_segments[uid]),
                "name": seg.get("speaker", "SPEAKER_00"),
                "start": seg.get("start", 0) - utterance_offsets[-1],
                "end": seg.get("end", 0) - utterance_offsets[-1],
                "text": seg.get("text", "").strip(),
            }
            utterance_segments[uid].append(named_seg)
            utterance_transcripts[uid].append(seg)
            all_named_segments.append(named_seg)
            full_transcript["segments"].append(seg)

    # Identify speakers across the window
    diarization_segments = [
        {
            "speaker": seg.get("speaker", "SPEAKER_00"),
            "start": seg.get("start", 0),
            "end": seg.get("end", 0),
        }
        for seg in batch_segments
        if seg.get("speaker")
    ]

    speakers = await identify_speakers(diarization_segments, audio_list[0], user_id)
    speaker_map = {s.get("speaker", ""): s.get("name", "Unknown") for s in speakers}

    # Update named segments with speaker names
    for named_seg in all_named_segments:
        speaker_id = named_seg["name"]
        named_seg["name"] = speaker_map.get(speaker_id, speaker_id)

    for uid, segments in utterance_segments.items():
        for named_seg in segments:
            speaker_id = named_seg["name"]
            named_seg["name"] = speaker_map.get(speaker_id, speaker_id)

    # Update each utterance in the database with its segments
    for utt in utterances:
        uid = utt["utterance_id"]
        utt_named = utterance_segments[uid]
        utt_transcript = {"segments": utterance_transcripts[uid]}
        await db.update_session_utterance(session_id, uid, utt_transcript, utt_named)

    logger.info(
        "Session %d: window [%s, %s] transcribed: %d segments, %d speakers",
        session_id, window_start, window_end,
        len(all_named_segments), len(speaker_map),
    )

    return {
        "all_named_segments": all_named_segments,
        "full_transcript": full_transcript,
        "speaker_map": speaker_map,
    }


# ── Hourly reprocessing ────────────────────────────────────────────


async def _reprocess_session(session: dict):
    """Batch transcribe session audio, summarize, save recording.

    Splits long sessions into 30-minute transcription windows to avoid
    ffmpeg timeouts, then combines results into a single recording.
    """
    session_id = session["id"]
    t_start = time.monotonic()
    CHUNK_MINUTES = 30

    logger.info("Session %d: starting reprocess", session_id)

    utterances = await db.get_session_all_utterances(session_id)
    if not utterances:
        logger.warning("Session %d has no utterances, marking processed and skipping", session_id)
        await db.mark_session_processed(session_id)
        return

    logger.info("Session %d: found %d utterances", session_id, len(utterances))

    # Determine full time range from utterances
    first = utterances[0]["created_at"].replace(tzinfo=None)
    last = utterances[-1]["created_at"].replace(tzinfo=None)
    total_minutes = (last - first).total_seconds() / 60
    logger.info(
        "Session %d: time range [%s, %s] (%.1f minutes)",
        session_id, first, last, total_minutes,
    )

    # Split into 30-minute chunks (no overlap — segments map to utterances by timestamp)
    all_named_segments = []
    full_transcript = {"segments": []}
    combined_speaker_map = {}

    # Build chunk boundaries from utterance timestamps
    chunk_starts = [first]
    chunk_start = first
    while chunk_start < last:
        chunk_start = chunk_start + timedelta(minutes=CHUNK_MINUTES)
        if chunk_start < last:
            chunk_starts.append(chunk_start)
    chunk_starts.append(last + timedelta(seconds=10))

    for i in range(len(chunk_starts) - 1):
        window_start = chunk_starts[i]
        window_end = chunk_starts[i + 1]
        chunk_num = i + 1
        logger.info(
            "Session %d: chunk %d/%d [%s, %s]",
            session_id, chunk_num, len(chunk_starts) - 1, window_start, window_end,
        )

        t_chunk = time.monotonic()
        result = await transcribe_window(session, window_start, window_end)
        chunk_elapsed = time.monotonic() - t_chunk

        segs = result["all_named_segments"]
        logger.info(
            "Session %d: chunk %d done in %.1fs: %d segments",
            session_id, chunk_num, chunk_elapsed, len(segs),
        )

        all_named_segments.extend(segs)
        full_transcript["segments"].extend(result["full_transcript"]["segments"])
        combined_speaker_map.update(result["speaker_map"])

    logger.info(
        "Session %d: transcription complete: %d total segments across %d chunks",
        session_id, len(all_named_segments), len(chunk_starts) - 1,
    )

    if not all_named_segments:
        logger.warning("Session %d: no segments from transcription, skipping save", session_id)
        await db.mark_session_processed(session_id)
        return

    # LLM summarization
    t_llm = time.monotonic()
    logger.info("Session %d: calling LLM summarize...", session_id)
    llm_result = summarize(all_named_segments)
    logger.info(
        "Session %d: LLM summarize returned in %.1fs",
        session_id, time.monotonic() - t_llm,
    )

    # Get audio filenames for the recording
    audio_files = await db.get_recording_audio_filenames(session_id)
    first_audio = audio_files[0] if audio_files else ""

    # Check if recording already exists (reprocessing) vs first processing
    existing_recording = await db.get_recording(session["user_id"], session_id)

    # Save (or update) recording — preserve original session start time
    category = llm_result.get("category", "not_meaningful")
    recording_id = await db.save_session_recording(
        session["user_id"], session_id, full_transcript,
        all_named_segments, llm_result, first_audio,
        session_timestamp=session["started_at"],
        category=category,
    )
    logger.info("Session %d: saved recording id=%d", session_id, recording_id)

    # Save todos only on first processing — never regenerate on reprocessing
    if existing_recording is None:
        todos = llm_result.get("todos", [])
        if todos:
            await db.save_todos(recording_id, session["user_id"], todos)

    # Save decisions — always overwrite (opposite of todos)
    decisions = llm_result.get("decisions", [])
    if decisions:
        await db.save_decisions(recording_id, session["user_id"], decisions)

    # Mark session as processed
    await db.mark_session_processed(session_id)
    logger.info(
        "Session %d reprocessed in %.1fs: %d segments, %d speakers, %d todos",
        session_id,
        time.monotonic() - t_start,
        len(all_named_segments),
        len(combined_speaker_map),
        len(llm_result.get("todos", [])),
    )

    # Update daily summary for this session's date
    try:
        session_date = session["started_at"]
        if isinstance(session_date, datetime):
            session_date = session_date.date()
        await _daily_reprocess_user(session["user_id"], session_date)
    except Exception:
        logger.exception("Error updating daily summary after session %d reprocess", session_id)


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
            logger.info(
                "Hourly reprocess: %d session(s) to process%s",
                len(sessions),
                " [session ids: %s]" % [s["id"] for s in sessions] if sessions else "",
            )
            for session in sessions:
                logger.info(
                    "Hourly reprocess: starting session %d (user=%d, started=%s)",
                    session["id"], session["user_id"], session["started_at"],
                )
                try:
                    await _reprocess_session(session)
                except Exception:
                    logger.exception(
                        "Error reprocessing session %d", session["id"]
                    )
        except Exception:
            logger.exception("Hourly reprocess loop error")


# ── Daily reprocessing ─────────────────────────────────────────────


async def _daily_reprocess_user(user_id: int, target_date=None):
    """Generate a daily summary from all session transcripts for a given date.

    No audio reprocessing — just collects existing transcripts and sends
    them to the LLM with a Work/Personal prompt.

    Args:
        user_id: The user to summarize for.
        target_date: A date object or datetime. If None, uses yesterday.
    """
    from datetime import timedelta

    from lifelog.pipeline.llm import summarize_day

    if target_date is None:
        now = datetime.now(UTC)
        target_date = (now - timedelta(days=1)).date()
    elif isinstance(target_date, datetime):
        target_date = target_date.date()

    day_start = datetime.combine(target_date, datetime.min.time()).replace(tzinfo=None)
    day_end = day_start + timedelta(days=1)

    sessions = await db.get_sessions_by_date_range(user_id, day_start, day_end)
    if not sessions:
        logger.info("Daily reprocess: user %d has no sessions for %s", user_id, target_date)
        return

    # Collect all utterance transcripts from all sessions for the day
    all_lines = []
    for session in sessions:
        utterances = await db.get_session_all_utterances(session["id"])
        for utt in utterances:
            transcript = utt.get("transcript", {})
            if isinstance(transcript, str):
                import json
                transcript = json.loads(transcript)
            segments = transcript.get("segments", [])
            for seg in segments:
                text = seg.get("text", "").strip()
                if text:
                    speaker = seg.get("speaker", "Unknown")
                    all_lines.append(f"[{session['started_at']}] {speaker}: {text}")

    if not all_lines:
        logger.info("Daily reprocess: user %d has no transcripts for %s", user_id, target_date)
        return

    combined = "\n".join(all_lines)
    logger.info(
        "Daily reprocess: user %d, %d sessions, %d transcript lines",
        user_id, len(sessions), len(all_lines),
    )

    # Generate daily summary via LLM
    result = summarize_day(combined)
    daily_summary = result.get("daily_summary", "")

    # Store daily summary (overwrites existing)
    await db.save_daily_summary(user_id, target_date, {"daily_summary": daily_summary})

    logger.info(
        "Daily summary for user %d on %s: %d chars",
        user_id, target_date, len(daily_summary),
    )
