"""
Ingestion from PostgreSQL into Meilisearch.

Used to:
  - Index a single recording after session finalization (worker hook).
  - Rebuild the full index for a user (reindex endpoint).

Each recording/session produces one document per:
  - Transcript turn  (kind="turn")
  - Summary          (kind="summary")
  - Decision         (kind="decision")
  - Todo             (kind="todo")

The conversation_id is the recording.id.  The turn index for kind="turn" documents
is the sequential segment index within that recording's transcript.
"""

import json
from datetime import datetime

import structlog

from lifelog import database as db
from lifelog import search

logger = structlog.get_logger()


def _parse_timestamp(value) -> str:
    """Return an ISO date string YYYY-MM-DD from a datetime or string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and value:
        return value[:10]
    return ""


def _speaker_names_from_recording(recording: dict) -> list[str]:
    """Extract distinct speaker names from a recording's speakers JSONB list."""
    speakers = recording.get("speakers") or []
    if isinstance(speakers, str):
        try:
            speakers = json.loads(speakers)
        except (json.JSONDecodeError, ValueError):
            return []
    names = []
    for s in speakers:
        if isinstance(s, dict):
            name = s.get("name") or ""
        else:
            name = str(s) if s else ""
        if name and name not in names:
            names.append(name)
    return names


def _extract_turns(recording: dict) -> list[dict]:
    """Yield turn dicts with index from a recording's transcript JSONB.

    Each turn: { "index": int, "text": str, "speaker": str }
    """
    transcript = recording.get("transcript") or {}
    if isinstance(transcript, str):
        try:
            transcript = json.loads(transcript)
        except (json.JSONDecodeError, ValueError):
            return []
    segments = (
        transcript if isinstance(transcript, list) else transcript.get("segments") or []
    )
    for i, seg in enumerate(segments):
        text = seg.get("text") or ""
        speaker = seg.get("speaker") or seg.get("name") or ""
        if text.strip():
            yield {"index": i, "text": text.strip(), "speaker": speaker}


async def ingest_recording(user_id: int, recording_id: int) -> int:
    """Fetch a recording and upsert each of its documents into Meilisearch.

    Returns the number of documents indexed.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT r.*, s.status AS session_status, s.ended_at AS session_ended_at
            FROM recordings r
            LEFT JOIN sessions s ON r.session_id = s.id
            WHERE r.id = $1 AND r.user_id = $2
            """,
            recording_id,
            user_id,
        )

    if not row:
        logger.warning(
            "ingest_recording_not_found", recording_id=recording_id, user_id=user_id
        )
        return 0

    recording = dict(row)

    title = recording.get("title") or ""
    timestamp = _parse_timestamp(recording.get("timestamp"))
    speakers = _speaker_names_from_recording(recording)

    count = 0

    # ── Turns ────────────────────────────────────────────────────────
    for turn in _extract_turns(recording):
        search.upsert_turn(
            user_id=user_id,
            conversation_id=recording_id,
            turn=turn["index"],
            text=turn["text"],
            speaker=turn["speaker"],
            timestamp=timestamp,
            title=title,
        )
        count += 1

    # ── Summary ───────────────────────────────────────────────────────
    summary = recording.get("summary") or ""
    long_summary = recording.get("long_summary") or ""
    summary_text = long_summary if long_summary else summary
    if summary_text:
        search.upsert_summary(
            user_id=user_id,
            conversation_id=recording_id,
            text=summary_text,
            participants=speakers,
            date=timestamp,
            title=title,
        )
        count += 1

    # ── Decisions ─────────────────────────────────────────────────────
    decisions = recording.get("decisions") or []
    if isinstance(decisions, str):
        try:
            decisions = json.loads(decisions)
        except (json.JSONDecodeError, ValueError):
            decisions = []
    for i, d in enumerate(decisions):
        if isinstance(d, dict):
            text = d.get("decision") or ""
        else:
            text = str(d) if d else ""
        if text:
            search.upsert_decision(
                user_id=user_id,
                conversation_id=recording_id,
                turn=i,
                text=text,
                title=title,
            )
            count += 1

    # ── Todos ─────────────────────────────────────────────────────────
    todos = recording.get("todos") or []
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except (json.JSONDecodeError, ValueError):
            todos = []
    for i, t in enumerate(todos):
        if isinstance(t, dict):
            text = t.get("task") or ""
            status = "done" if t.get("completed") else "open"
        else:
            text = str(t) if t else ""
            status = "open"
        if text:
            search.upsert_todo(
                user_id=user_id,
                conversation_id=recording_id,
                turn=i,
                text=text,
                status=status,
                title=title,
            )
            count += 1

    logger.info("ingest_recording_done", recording_id=recording_id, docs_indexed=count)
    return count


async def ingest_all(user_id: int) -> int:
    """Full re-index: ingest every recording for a user.

    Returns the total number of documents indexed.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.id
            FROM recordings r
            WHERE r.user_id = $1
            ORDER BY r.id
            """,
            user_id,
        )

    recording_ids = [row["id"] for row in rows]
    total = 0
    for rid in recording_ids:
        try:
            total += await ingest_recording(user_id, rid)
        except (json.JSONDecodeError, ValueError):
            logger.exception(
                "ingest_all_recording_error", recording_id=rid, user_id=user_id
            )

    logger.info(
        "ingest_all_done",
        user_id=user_id,
        total_docs=total,
        recording_count=len(recording_ids),
    )
    return total
