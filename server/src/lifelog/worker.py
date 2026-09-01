"""Background worker for encrypted upload and asynchronous transcription jobs."""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx

import lifelog.database as db
from lifelog.config import settings
from lifelog.crypto import audio_crypto
from lifelog.database import delete_utterance_chunks, get_utterance_chunks
from lifelog.pipeline.llm import summarize

logger = logging.getLogger("lifelog.worker")
POLL_INTERVAL = 60.0
_ALLOWED_AUDIO_LABELS = lambda name: name not in {"Unknown", ""}
_MICROSECOND = timedelta(microseconds=1)


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


async def complete_utterance(user_id: int, utterance_id: int, recording_id: int | None):
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
            "SELECT id, encryption_secret, key_salt FROM users WHERE id = $1",
            user_id,
        )
        return dict(row) if row else None


async def process_utterance(user_id: int, utterance_id: int):
    """Encrypt audio and assign to a session for later quick transcription."""
    start = time.monotonic()
    logger.info("Processing utterance %d/%d", user_id, utterance_id)
    chunks = await get_utterance_chunks(user_id, utterance_id)
    if not chunks:
        logger.warning("No chunks found for utterance %d/%d", user_id, utterance_id)
        await fail_utterance(user_id, utterance_id, "no chunks found")
        return

    user_secrets = await get_user_secret(user_id)
    if not user_secrets:
        await fail_utterance(user_id, utterance_id, "user not found")
        return
    encryption_secret = user_secrets["encryption_secret"]
    key_salt = bytes(user_secrets["key_salt"])
    audio_filenames = []
    for index, chunk in enumerate(chunks):
        filename = audio_crypto.encrypt_audio(
            chunk["audio_bytes"], encryption_secret, key_salt
        )
        audio_filenames.append(filename)
        if settings.verify_audio_writes:
            audio_crypto.decrypt_audio(filename, encryption_secret, key_salt)
        logger.debug("Utterance %d/%d chunk %d encrypted", user_id, utterance_id, index)
    await delete_utterance_chunks(user_id, utterance_id)

    queue_entry = await db.get_utterance_queue_entry(user_id, utterance_id)
    utterance_time = (
        queue_entry["created_at"]
        if queue_entry
        else datetime.now(UTC).replace(tzinfo=None)
    )
    active_session = await db.get_active_session(user_id)
    if active_session:
        last_time = await db.get_last_utterance_time(active_session["id"])
        ref_time = last_time or active_session["started_at"]
        gap_minutes = (
            utterance_time - ref_time.replace(tzinfo=None)
        ).total_seconds() / 60
        if gap_minutes <= settings.session_gap_minutes:
            session_id = active_session["id"]
        else:
            await db.end_session(active_session["id"])
            try:
                await _reprocess_session(active_session)
            except Exception:
                logger.exception("Error queuing ended session %d", active_session["id"])
            session_id = await db.create_session(user_id, utterance_time)
    else:
        session_id = await db.create_session(user_id, utterance_time)

    audio_filename = audio_filenames[0] if audio_filenames else ""
    await db.append_session_utterance(
        session_id,
        utterance_id,
        audio_filename,
        {},
        [],
        utterance_timestamp=utterance_time,
    )
    await complete_utterance(user_id, utterance_id, None)
    logger.info(
        "Utterance %d/%d assigned to session %d in %.2fs",
        user_id,
        utterance_id,
        session_id,
        time.monotonic() - start,
    )


async def _create_session_quick_jobs() -> None:
    """Create one quick job per active session covering all untranscribed utterances.

    Groups all utterances without transcripts from each active session into a
    single sliding-window quick job, so the transcription worker can batch
    them together for better ASR quality (longer audio = better WhisperX output).
    """
    sessions = await db.get_active_sessions_with_utterances()
    for session in sessions:
        # Find utterances in this session that have no transcript yet
        # (transcript is NULL or segments array is empty)
        utterances = await db.get_session_all_utterances(session["id"])
        untranscribed = [
            u
            for u in utterances
            if not u.get("transcript")
            or not u["transcript"].get("segments")
            or len(u["transcript"].get("segments", [])) == 0
        ]
        if not untranscribed:
            continue
        # Check if there's already a pending quick job for this session
        existing = await db.get_pending_session_quick_job(session["id"])
        if existing:
            logger.debug(
                "Session %d already has pending quick job %s",
                session["id"],
                existing["id"],
            )
            continue
        # Create one job for untranscribed utterances in this session,
        # bounded as a rolling window past the last completed quick job
        # so each batch transcribes only newly-arrived audio — never
        # repainting the full session history. The window floor is
        # ``last_completed + 1µs`` when we have one; otherwise we fall
        # back to ``window_end - quick_window_minutes`` so first-ever
        # jobs still respect the rolling cap.
        utterance_ids = [u["utterance_id"] for u in untranscribed]
        window_end = untranscribed[-1]["created_at"].replace(tzinfo=None)
        user_settings = await db.get_user_settings(session["user_id"])
        last_completed = await db.get_latest_completed_quick_job(session["id"])
        if last_completed and last_completed.get("completed_at"):
            window_floor = (
                last_completed["completed_at"].replace(tzinfo=None) + _MICROSECOND
            )
        else:
            window_floor = window_end - timedelta(
                minutes=max(1, settings.quick_window_minutes)
            )
        window_start = max(
            window_floor,
            untranscribed[0]["created_at"].replace(tzinfo=None),
        )
        language = user_settings.get("language", "auto")
        try:
            await db.create_session_quick_job(
                session["id"],
                utterance_ids,
                window_start,
                window_end,
                language=language,
            )
            logger.info(
                "Session %d: queued quick job for %d untranscribed utterances [%s, %s]",
                session["id"],
                len(utterance_ids),
                window_start.isoformat(),
                window_end.isoformat(),
            )
        except Exception:
            logger.exception(
                "Error creating session quick job for session %d", session["id"]
            )


async def _apply_quick_transcripts() -> None:
    """Apply completed quick jobs: map combined diarized segments back to individual utterances."""
    for job in await db.get_completed_quick_jobs():
        try:
            result = job.get("result") or {}
            if isinstance(result, str):
                import json

                result = json.loads(result)
            session_id = result.get("session_id") or job.get("session_id")
            utterance_ids = result.get("utterance_ids", [])
            if not utterance_ids:
                # Legacy per-utterance job: single-utterance path
                utterance_id = result.get("utterance_id") or job.get("chunk_index")
                if utterance_id is None:
                    utterance_id = (result.get("utterances") or [{}])[0].get(
                        "utterance_id"
                    )
                if utterance_id is None:
                    raise ValueError("quick result has no utterance_id")
                segments = result.get("segments", [])
                if not isinstance(segments, list):
                    raise TypeError("quick result segments is not a list")
                await db.update_session_utterance_transcript(
                    job["session_id"], utterance_id, {"segments": segments}
                )
                await db.mark_quick_job_applied(job["id"])
                continue
            # Session-level job: map combined segments back to individual utterances
            window_start = job.get("window_start")
            window_end = job.get("window_end")
            if window_start and window_end:
                utterances = await db.get_session_utterances_in_range(
                    session_id, window_start, window_end
                )
            else:
                utterances = await db.get_session_all_utterances(session_id)
            utterances = [
                u for u in utterances if u["utterance_id"] in set(utterance_ids)
            ]
            if not utterances:
                logger.warning("No utterances found for quick job %s", job["id"])
                await db.mark_quick_job_applied(job["id"])
                continue
            # Build an utterance → combined-stream-seconds span lookup from
            # the worker's reported ``utterance_spans``. Each entry declares
            # where the utterance's audio sits in the concatenated waveform
            # so a WhisperX segment overlaps exactly one span. We fall back
            # to the wall-clock offsets only for legacy results that
            # arrived without the spans field.
            span_by_utt: dict[int, tuple[float, float]] = {}
            for span in result.get("utterance_spans") or []:
                utt_id = span.get("utterance_id")
                if utt_id is None:
                    continue
                try:
                    sp_start = float(span["start"])
                    sp_end = float(span["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                span_by_utt[utt_id] = (sp_start, sp_end)
            # Per-utterance destination buffer; we always write into this
            # even when the span map is empty.
            utterance_segments: dict[int, list] = {
                u["utterance_id"]: [] for u in utterances
            }
            all_segments = result.get("segments", []) or []
            if span_by_utt:
                # Use a midpoint-overlap rule. Spans never overlap, so a
                # single pass per segment is sufficient; we still pick
                # the largest-overlap span to be robust against noise in
                # the diarizer.
                for seg in all_segments:
                    seg_start = float(seg.get("start", 0.0) or 0.0)
                    seg_end = float(seg.get("end", 0.0) or 0.0)
                    text = (seg.get("text") or "").strip()
                    speaker = seg.get("speaker", "SPEAKER_00")
                    midpoint = (seg_start + seg_end) / 2.0
                    assigned: int | None = None
                    best_overlap = -1.0
                    for utt_id, (sp_start, sp_end) in span_by_utt.items():
                        if sp_start <= midpoint < sp_end:
                            overlap = min(seg_end, sp_end) - max(seg_start, sp_start)
                            if overlap > best_overlap:
                                best_overlap = overlap
                                assigned = utt_id
                    if assigned is None:
                        # Span map gaps during diarizer drift — drop seg.
                        continue
                    utt_start, _ = span_by_utt[assigned]
                    utterance_segments[assigned].append(
                        {
                            "start": max(0.0, seg_start - utt_start),
                            "end": max(seg_start - utt_start, seg_end - utt_start),
                            "text": text,
                            "speaker": speaker,
                        }
                    )
            else:
                # Legacy wall-clock partition: assign each segment to the
                # utterance whose [off_start, off_end) bracket still
                # contains seg_start. Drift from clock skew lands in the
                # nearest neighbour.
                offsets: dict[int, float] = {}
                first_ts = utterances[0]["created_at"].replace(tzinfo=None)
                for utt in utterances:
                    offsets[utt["utterance_id"]] = (
                        utt["created_at"].replace(tzinfo=None) - first_ts
                    ).total_seconds()
                for seg in all_segments:
                    seg_start = seg.get("start", 0.0)
                    seg_end = seg.get("end", 0.0)
                    text = seg.get("text", "").strip()
                    speaker = seg.get("speaker", "SPEAKER_00")
                    assigned = False
                    for i, utt in enumerate(utterances):
                        off_start = offsets[utt["utterance_id"]]
                        if i + 1 < len(utterances):
                            off_end = offsets[utterances[i + 1]["utterance_id"]]
                        else:
                            # Last utterance: cover rest of combined audio
                            if i > 0:
                                prev_end = offsets[utterances[i - 1]["utterance_id"]]
                                off_end = (
                                    off_start + (off_start - prev_end)
                                    if off_start > prev_end
                                    else 2.0
                                )
                            else:
                                off_end = off_start + 2.0
                        if off_start <= seg_start < off_end:
                            utterance_segments[utt["utterance_id"]].append(
                                {
                                    "start": seg_start - off_start,
                                    "end": seg_end - off_start,
                                    "text": text,
                                    "speaker": speaker,
                                }
                            )
                            assigned = True
                            break
                    if not assigned and utterances:
                        last = utterances[-1]
                        off_start = offsets[last["utterance_id"]]
                        utterance_segments[last["utterance_id"]].append(
                            {
                                "start": seg_start - off_start,
                                "end": seg_end - off_start,
                                "text": text,
                                "speaker": speaker,
                            }
                        )
            for utt in utterances:
                await db.update_session_utterance_transcript(
                    session_id,
                    utt["utterance_id"],
                    {"segments": utterance_segments.get(utt["utterance_id"], [])},
                )
            await db.mark_quick_job_applied(job["id"])
            logger.info(
                "Quick job %d applied: %d utterances, %d combined segments",
                job["id"],
                len(utterances),
                len(all_segments),
            )
        except Exception:
            logger.exception(
                "Unable to apply quick transcription job %s", job.get("id")
            )


def _window_ranges(utterances: list[dict]) -> list[tuple[datetime, datetime]]:

    first = utterances[0]["created_at"].replace(tzinfo=None)
    last = utterances[-1]["created_at"].replace(tzinfo=None)
    duration = timedelta(minutes=max(1, settings.reprocess_chunk_minutes))
    count = max(1, int((last - first) / duration) + 1)
    return [
        (
            first + index * duration,
            min(first + (index + 1) * duration, last + timedelta(seconds=1)),
        )
        for index in range(count)
    ]


async def _reprocess_session(session: dict):
    """Queue missing full transcription jobs for an ended session."""
    session_id = session["id"]
    utterances = await db.get_session_all_utterances(session_id)
    if not utterances:
        logger.warning("Session %d has no utterances, marking processed", session_id)
        await db.mark_session_processed(session_id)
        return
    existing = await db.get_transcription_jobs(session_id)
    existing_by_chunk = {
        job.get("chunk_index"): job
        for job in existing
        if (job.get("job_type") or "full") == "full"
    }
    for chunk_index, (window_start, window_end) in enumerate(
        _window_ranges(utterances)
    ):
        job = existing_by_chunk.get(chunk_index)
        if job is not None:
            if job.get("status") == "failed":
                logger.error(
                    "Session %d chunk %d has terminal failed transcription job",
                    session_id,
                    chunk_index,
                )
            continue
        settings = await db.get_user_settings(session["user_id"])
        language = settings.get("language", "auto")
        await db.create_transcription_job(
            session_id, window_start, window_end, chunk_index, language=language
        )
        logger.info(
            "Session %d queued full transcription chunk %d", session_id, chunk_index
        )


def _shifted_segments(segments: list[dict], offset: float) -> list[dict]:
    shifted = []
    for segment in segments:
        item = dict(segment)
        if isinstance(item.get("start"), (int, float)):
            item["start"] += offset
        if isinstance(item.get("end"), (int, float)):
            item["end"] += offset
        shifted.append(item)
    return shifted


def _partition_segments(
    segments: list[dict],
    gap_threshold_seconds: float = 300.0,
) -> list[list[dict]]:
    """Partition speaker_segments into groups separated by gaps >= gap_threshold_seconds.

    Returns a list of partitions, each a list of segments. Partition[0] is the
    first group of segments before any large gap. Partition[1+] are segments
    after each >=5-minute gap.
    """
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda s: s.get("start", 0))
    partitions: list[list[dict]] = []
    current: list[dict] = []
    for seg in sorted_segs:
        if current:
            prev_end = current[-1].get("end", 0)
            gap = seg.get("start", 0) - prev_end
            if gap >= gap_threshold_seconds:
                # Gap found — start a new partition
                partitions.append(current)
                current = []
        current.append(seg)
    if current:
        partitions.append(current)
    return partitions


def _persist_partition_segments(
    partition: list[dict],
    user: dict,
) -> list[dict]:
    """Encrypt audio payloads and build persisted segment list for one partition."""
    import base64

    persisted = []
    for segment in partition:
        audio_payload = segment.get("audio")
        if audio_payload:
            try:
                audio_filename = audio_crypto.encrypt_audio(
                    base64.b64decode(audio_payload),
                    user["encryption_secret"],
                    bytes(user["key_salt"]),
                )
            except Exception:
                logger.warning("Skipping invalid speaker segment audio", exc_info=True)
                continue
        else:
            audio_filename = ""
        persisted.append(
            {
                "speaker": segment.get("speaker", "Unknown"),
                "start": segment.get("start", 0),
                "end": segment.get("end", 0),
                "text": segment.get("text", ""),
                "audio_filename": audio_filename,
            }
        )
    return persisted


def _named_from_persisted(persisted: list[dict]) -> list[dict]:
    """Build named segment list (for LLM) from persisted segments."""
    return [
        {
            "name": seg["speaker"],
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        }
        for seg in persisted
    ]


def _offset_to_datetime(offset_seconds: float, base: datetime) -> datetime:
    """Convert an audio offset (seconds from session start) to an absolute datetime."""
    from datetime import timedelta

    return base + timedelta(seconds=offset_seconds)


def _normalise_summary(result: dict) -> dict:
    result = dict(result)
    summary = result.get("summary", "")
    if isinstance(summary, dict):
        result["summary"] = summary.get("summary", str(summary))
    elif isinstance(summary, list):
        result["summary"] = "\n".join(str(item) for item in summary)
    else:
        result["summary"] = str(summary)
    category = result.get("category", "not_meaningful")
    if category is None:
        category = "not_meaningful"
    elif not isinstance(category, str):
        category = (
            "\n".join(str(item) for item in category)
            if isinstance(category, list)
            else str(category)
        )
    result["category"] = category
    for key in ("todos", "calendar", "notes", "conversation_changes"):
        result.setdefault(key, [])
    return result


async def _auto_enroll_speakers(user: dict, speaker_segments: list[dict]) -> None:
    """Enroll raw speaker labels from the current recording when possible."""
    from lifelog.pipeline.speaker_client import serialize_embedding

    voiceprints = await db.get_all_voiceprints(user["id"])
    known = {voiceprint["name"] for voiceprint in voiceprints}
    grouped: dict[str, list[bytes]] = {}
    for segment in speaker_segments:
        label = segment.get("speaker") or segment.get("name") or "Unknown"
        filename = segment.get("audio_filename")
        if label in {"Unknown", ""} or label in known or not filename:
            continue
        try:
            audio = audio_crypto.decrypt_audio(
                filename, user["encryption_secret"], bytes(user["key_salt"])
            )
        except Exception:
            logger.warning(
                "Skipping corrupt audio for speaker '%s'", label, exc_info=True
            )
            continue
        grouped.setdefault(label, []).append(audio)

    for label, audio_files in grouped.items():
        if not audio_files:
            continue
        opus_audio = audio_files[0]
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{settings.speaker_id_url}/enroll",
                    params={"name": label},
                    files={"file": ("speaker.opus", opus_audio, "audio/opus")},
                )
                response.raise_for_status()
                embedding = response.json()["embedding"]
            await db.save_voiceprint(user["id"], label, serialize_embedding(embedding))
            known.add(label)
            logger.info("Auto-enrolled voiceprint for '%s'", label)
        except Exception:
            logger.exception("Unable to auto-enroll speaker '%s'", label)


async def _enroll_session_speakers(
    user: dict, all_partitions: list[list[dict]]
) -> None:
    """Enroll speakers from ALL partitions, not just partition 0.

    Called after all partitions are saved so that speakers appearing only in
    partitions 1+ (after a >5-min gap) get enrolled for cross-recording matching.
    """
    from lifelog.pipeline.speaker_client import serialize_embedding

    voiceprints = await db.get_all_voiceprints(user["id"])
    known = {vp["name"] for vp in voiceprints}

    # Collect all unique speakers across all partitions
    all_speakers: dict[str, bytes] = {}
    for partition in all_partitions:
        for segment in partition:
            label = segment.get("speaker") or segment.get("name") or "Unknown"
            if label in {"Unknown", ""} or label in known or label in all_speakers:
                continue
            filename = segment.get("audio_filename")
            if not filename:
                continue
            try:
                audio = audio_crypto.decrypt_audio(
                    filename, user["encryption_secret"], bytes(user["key_salt"])
                )
                all_speakers[label] = audio
            except Exception:
                logger.warning(
                    "Skipping corrupt audio for speaker '%s'", label, exc_info=True
                )

    for label, opus_audio in all_speakers.items():
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(
                    f"{settings.speaker_id_url}/enroll",
                    params={"name": label},
                    files={"file": ("speaker.opus", opus_audio, "audio/opus")},
                )
                response.raise_for_status()
                embedding = response.json()["embedding"]
            await db.save_voiceprint(user["id"], label, serialize_embedding(embedding))
            known.add(label)
            logger.info("Enrolled speaker '%s' from session partitions", label)
        except Exception:
            logger.exception(
                "Unable to enroll speaker '%s' from session partitions", label
            )


async def _reidentify_recording(user: dict, recording: dict) -> None:
    """Re-identify raw labels and update all persisted recording structures."""
    from lifelog.pipeline.speaker_client import identify_speakers

    raw_segments = recording.get("speaker_segments") or []
    # asyncpg may return JSONB as a string (especially if double-encoded)
    segments: list = raw_segments
    if isinstance(raw_segments, str):
        import json

        try:
            parsed = json.loads(raw_segments)
            # May still be a string if double-encoded: try again
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            segments = parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError, TypeError):
            segments = []
    if not segments:
        filename = recording.get("audio_filename")
        if not filename:
            return
        try:
            audio = audio_crypto.decrypt_audio(
                filename, user["encryption_secret"], bytes(user["key_salt"])
            )
            identified = await identify_speakers(
                recording.get("speakers", []), audio, user["id"]
            )
            await db.update_recording_speakers(recording["id"], identified)
        except Exception:
            logger.exception("Unable to re-identify recording %s", recording.get("id"))
        return
    updated = []
    labels: dict[str, str] = {}
    for segment in segments:
        if isinstance(segment, str):
            import json

            try:
                segment = json.loads(segment)
            except (json.JSONDecodeError, ValueError):
                continue
        item = (
            dict(segment)
            if isinstance(segment, dict)
            else (segment.model_dump() if hasattr(segment, "model_dump") else segment)
        )
        raw = item.get("speaker") or item.get("name") or "Unknown"
        filename = item.get("audio_filename")
        if filename:
            try:
                audio = audio_crypto.decrypt_audio(
                    filename, user["encryption_secret"], bytes(user["key_salt"])
                )
                identified = await identify_speakers(
                    [{"speaker": raw, "start": 0, "end": 1}],
                    audio,
                    user["id"],
                    audio_format="wav",
                )
                if identified and identified[0].get("name") not in {None, "Unknown"}:
                    labels[raw] = identified[0]["name"]
            except Exception:
                logger.warning(
                    "Unable to re-identify segment for '%s'", raw, exc_info=True
                )
        item["speaker"] = labels.get(raw, raw)
        updated.append(item)
    speakers = [
        {
            "id": index,
            "name": item["speaker"],
            "start": item.get("start", 0),
            "end": item.get("end", 0),
            "text": item.get("text", ""),
        }
        for index, item in enumerate(updated)
    ]
    await db.update_recording_speaker_data(recording["id"], speakers, updated)


async def _finalize_completed_sessions() -> None:
    """Persist sessions after every required full job is complete.

    If a session has >5-minute gaps in its speaker_segments, the session is
    split into multiple recordings (one per partition). The gap audio is
    discarded — only the transcribed content is preserved.
    """
    sessions = await db.get_sessions_for_reprocessing()
    for session in sessions:
        try:
            jobs = await db.get_transcription_jobs(session["id"])
            full_jobs = [
                job for job in jobs if (job.get("job_type") or "full") == "full"
            ]
            if not full_jobs:
                continue
            if any(
                job.get("status") in {"pending", "processing", "failed"}
                for job in full_jobs
            ):
                continue
            if not all(job.get("status") == "done" for job in full_jobs):
                continue
            first = min(job["window_start"] for job in full_jobs)
            transcript_segments = []
            speaker_segments = []
            speaker_map = {}
            for job in sorted(
                full_jobs, key=lambda item: (item.get("chunk_index") or 0, item["id"])
            ):
                result = job.get("result") or {}
                if isinstance(result, str):
                    import json

                    result = json.loads(result)
                offset = (job["window_start"] - first).total_seconds()
                transcript_segments.extend(
                    _shifted_segments(result.get("segments", []), offset)
                )
                for segment in result.get("speaker_segments", []):
                    item = dict(segment)
                    item.pop("audio_filename", None)
                    item["start"] = float(item.get("start", 0)) + offset
                    item["end"] = float(item.get("end", 0)) + offset
                    speaker_segments.append(item)
                speaker_map.update(result.get("speaker_map", {}))
            speaker_segments.sort(key=lambda item: item.get("start", 0))

            # Detect gap splits (>5-minute gaps between segments)
            partitions = _partition_segments(speaker_segments)
            if not partitions:
                logger.warning(
                    "Session %d has no speaker segments to persist, skipping",
                    session["id"],
                )
                await db.mark_session_processed(session["id"])
                continue
            user = await get_user_secret(session["user_id"])
            settings_row = await db.get_user_settings(session["user_id"])
            llm_context = settings_row.get("llm_context", "")
            audio_files = await db.get_recording_audio_filenames(session["id"])
            session_start = session["started_at"]
            if session_start is None:
                session_start = datetime.now(tz=UTC)

            if len(partitions) == 1:
                # No split — existing single-recording path
                partition = partitions[0]
                persisted = _persist_partition_segments(partition, user)
                named = _named_from_persisted(persisted)
                llm_result = _normalise_summary(
                    summarize(named, llm_context=llm_context)
                )
                recording_id = await db.save_session_recording(
                    session["user_id"],
                    session["id"],
                    {"segments": transcript_segments},
                    named,
                    llm_result,
                    audio_files[0] if audio_files else "",
                    speaker_segments=persisted,
                    session_timestamp=session_start,
                    category=llm_result.get("category", "not_meaningful"),
                )
                if llm_result.get("todos"):
                    await db.save_todos(
                        recording_id, session["user_id"], llm_result["todos"]
                    )
                if llm_result.get("decisions"):
                    await db.save_decisions(
                        recording_id, session["user_id"], llm_result["decisions"]
                    )
                await db.mark_session_processed(session["id"])
                await _auto_enroll_speakers(user, persisted)
                current = await db.get_recording(user["id"], recording_id)
                if current:
                    await _reidentify_recording(user, current)
                for prior in await db.get_unknown_speakers(user["id"]):
                    if prior.get("id") != recording_id:
                        prior["encryption_secret"] = user["encryption_secret"]
                        prior["key_salt"] = user["key_salt"]
                        await _reidentify_recording(user, prior)
                try:
                    session_date = session["started_at"]
                    if isinstance(session_date, datetime):
                        session_date = session_date.date()
                    await _daily_reprocess_user(
                        user["id"], session_date, llm_context=llm_context
                    )
                except Exception:
                    logger.exception(
                        "Error updating daily summary after session %d", session["id"]
                    )
            else:
                # Gap split — create one recording per partition
                logger.info(
                    "Session %d split into %d partitions (gaps > 5 min)",
                    session["id"],
                    len(partitions),
                )
                # First partition gets the existing session-level summary + todos/decisions
                partition_0 = partitions[0]
                persisted_0 = _persist_partition_segments(partition_0, user)
                named_0 = _named_from_persisted(persisted_0)
                llm_0 = _normalise_summary(summarize(named_0, llm_context=llm_context))
                recording_id = await db.save_session_recording(
                    session["user_id"],
                    session["id"],
                    {"segments": transcript_segments},
                    named_0,
                    llm_0,
                    audio_files[0] if audio_files else "",
                    speaker_segments=persisted_0,
                    session_timestamp=session_start,
                    category=llm_0.get("category", "not_meaningful"),
                )
                if llm_0.get("todos"):
                    await db.save_todos(
                        recording_id, session["user_id"], llm_0["todos"]
                    )
                if llm_0.get("decisions"):
                    await db.save_decisions(
                        recording_id, session["user_id"], llm_0["decisions"]
                    )
                await db.mark_session_processed(session["id"])
                await _auto_enroll_speakers(user, persisted_0)
                all_persisted = [persisted_0]

                # Subsequent partitions — one new recording each, no todos/decisions
                for idx, partition in enumerate(partitions[1:], start=1):
                    persisted = _persist_partition_segments(partition, user)
                    all_persisted.append(persisted)
                    named = _named_from_persisted(persisted)
                    llm_n = _normalise_summary(
                        summarize(named, llm_context=llm_context)
                    )
                    # Rebase segment start/end relative to this partition
                    partition_offset = partition[0]["start"]
                    rebased = []
                    for seg in persisted:
                        item = dict(seg)
                        item["start"] = seg["start"] - partition_offset
                        item["end"] = seg["end"] - partition_offset
                        rebased.append(item)
                    audio_range_start = _offset_to_datetime(
                        partition_offset, session_start
                    )
                    audio_range_end = _offset_to_datetime(
                        partition[-1]["end"], session_start
                    )
                    try:
                        await db.save_partition_recording(
                            session["user_id"],
                            session["id"],
                            idx,
                            {"segments": []},  # no quick-transcript for partitions
                            named,
                            llm_n,
                            audio_files[0] if audio_files else "",
                            rebased,
                            audio_range_start,
                            audio_range_end,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to create partition %d recording for session %d",
                            idx,
                            session["id"],
                        )

                # Enroll any speakers from partitions 1+ that weren't in partition 0
                await _enroll_session_speakers(user, all_persisted)

                # Re-identify and daily summary after all partitions created
                current = await db.get_recording(user["id"], recording_id)
                if current:
                    await _reidentify_recording(user, current)
                for prior in await db.get_unknown_speakers(user["id"]):
                    if prior.get("id") != recording_id:
                        prior["encryption_secret"] = user["encryption_secret"]
                        prior["key_salt"] = user["key_salt"]
                        await _reidentify_recording(user, prior)
                try:
                    session_date = session["started_at"]
                    if isinstance(session_date, datetime):
                        session_date = session_date.date()
                    await _daily_reprocess_user(
                        user["id"], session_date, llm_context=llm_context
                    )
                except Exception:
                    logger.exception(
                        "Error updating daily summary after session %d", session["id"]
                    )

        except Exception:
            logger.exception("Error finalizing session %d", session["id"])


async def worker_loop():
    """Poll uploads, apply quick results, and orchestrate full jobs."""
    logger.info("Worker started, polling every %.0fs", POLL_INTERVAL)
    while True:
        try:
            for utterance in await get_pending_utterances():
                if not await claim_utterance(
                    utterance["user_id"], utterance["utterance_id"]
                ):
                    continue
                try:
                    await process_utterance(
                        utterance["user_id"], utterance["utterance_id"]
                    )
                except Exception as exc:
                    logger.exception(
                        "Error processing utterance %d/%d",
                        utterance["user_id"],
                        utterance["utterance_id"],
                    )
                    await fail_utterance(
                        utterance["user_id"], utterance["utterance_id"], str(exc)
                    )
            try:
                await _apply_quick_transcripts()
            except Exception:
                logger.exception("Error applying quick transcripts")
            try:
                await _create_session_quick_jobs()
            except Exception:
                logger.exception("Error creating session quick jobs")
            try:
                for session in await db.get_idle_active_sessions(
                    settings.session_gap_minutes
                ):
                    await db.end_session(session["id"])
                    try:
                        await _reprocess_session(session)
                    except Exception:
                        logger.exception("Error queuing idle session %d", session["id"])
            except Exception:
                logger.exception("Error ending idle sessions")
            try:
                await _finalize_completed_sessions()
            except Exception:
                logger.exception("Error finalizing completed sessions")
        except Exception:
            logger.exception("Worker poll error")
        await asyncio.sleep(POLL_INTERVAL)


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
                    session["id"],
                    session["user_id"],
                    session["started_at"],
                )
                try:
                    await _reprocess_session(session)
                except Exception:
                    logger.exception("Error reprocessing session %d", session["id"])
        except Exception:
            logger.exception("Hourly reprocess loop error")


# ── Daily reprocessing ─────────────────────────────────────────────


async def _daily_reprocess_user(user_id: int, target_date=None, llm_context: str = ""):
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
        logger.info(
            "Daily reprocess: user %d has no sessions for %s", user_id, target_date
        )
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
        logger.info(
            "Daily reprocess: user %d has no transcripts for %s", user_id, target_date
        )
        return

    combined = "\n".join(all_lines)
    logger.info(
        "Daily reprocess: user %d, %d sessions, %d transcript lines",
        user_id,
        len(sessions),
        len(all_lines),
    )

    # Generate daily summary via LLM
    result = summarize_day(combined, llm_context=llm_context)
    daily_summary = result.get("daily_summary", "")

    # Store daily summary (overwrites existing)
    await db.save_daily_summary(user_id, target_date, {"daily_summary": daily_summary})

    logger.info(
        "Daily summary for user %d on %s: %d chars",
        user_id,
        target_date,
        len(daily_summary),
    )
