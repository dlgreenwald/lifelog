import json
import logging
from datetime import UTC, datetime

import asyncpg

from lifelog.config import settings

logger = logging.getLogger("lifelog.database")

# ── Pure helpers ───────────────────────────────────────────────────


# ── Global connection pool
pool: asyncpg.Pool = None


async def _init_connection(conn):
    await conn.set_type_codec("json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_pool():
    """Initialize PostgreSQL connection pool (migrations run separately via migrate.py)."""
    global pool
    pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=5,
        max_size=20,
        ssl=settings.postgres_ssl,
        init=_init_connection,
    )


async def init_db():
    """Initialize pool and run migrations (for backwards compat)."""
    await init_pool()

    from alembic.config import Config

    from alembic import command

    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}",
    )

    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: command.upgrade(alembic_cfg, "head"))


# User operations
async def get_user_by_api_key(api_key: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, api_key, oidc_sub, name, encryption_secret, key_salt FROM users WHERE api_key = $1",
            api_key,
        )
        return dict(row) if row else None


async def get_user_by_oidc_sub(oidc_sub: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, api_key, oidc_sub, name, encryption_secret, key_salt FROM users WHERE oidc_sub = $1",
            oidc_sub,
        )
        return dict(row) if row else None


async def create_user(
    api_key: str | None = None, oidc_sub: str | None = None, name: str | None = None
) -> dict:
    import secrets

    encryption_secret = secrets.token_hex(32)
    key_salt = secrets.token_bytes(16)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (api_key, oidc_sub, name, encryption_secret, key_salt)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            api_key,
            oidc_sub,
            name,
            encryption_secret,
            key_salt,
        )
        return {
            "id": row["id"],
            "api_key": api_key,
            "oidc_sub": oidc_sub,
            "name": name,
            "encryption_secret": encryption_secret,
            "key_salt": key_salt,
        }


# Recording operations
async def save_recording(
    user_id: int,
    transcript: dict,
    named_segments: list,
    result: dict,
    audio_filename: str,
) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO recordings (user_id, timestamp, transcript, speakers,
                summary, todos, calendar, notes, conversation_changes, audio_filename)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
        """,
            user_id,
            datetime.now(UTC).replace(tzinfo=None),
            transcript,
            named_segments,
            result["summary"],
            result["todos"],
            result["calendar"],
            result["notes"],
            result.get("conversation_changes", []),
            audio_filename,
        )
        return row["id"]


async def get_recordings_by_date(
    user_id: int, date: str, category: str | None = None
) -> list[dict]:
    """Get all recordings for a user on a specific date (YYYY-MM-DD, Eastern Time).

    If category is provided, filter to that category.
    If category is None, show work and personal (exclude not_meaningful).
    """
    from datetime import date as _date
    date_obj = _date.fromisoformat(date)
    async with pool.acquire() as conn:
        if category is not None:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, summary, todos, calendar, notes, speakers, category,
                       session_id, partition_index, audio_range_start, audio_range_end
                FROM recordings
                WHERE user_id = $1
                  AND DATE(timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = $2
                  AND category = $3
                ORDER BY timestamp DESC
            """,
                user_id,
                date_obj,
                category,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, timestamp, summary, todos, calendar, notes, speakers, category,
                       session_id, partition_index, audio_range_start, audio_range_end
                FROM recordings
                WHERE user_id = $1
                  AND DATE(timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = $2
                  AND (category IS NULL OR category IN ('work', 'personal'))
                ORDER BY timestamp DESC
            """,
                user_id,
                date_obj,
            )
        return [dict(row) for row in rows]


async def get_recording(user_id: int, recording_id: int) -> dict | None:
    """Get a specific recording (must belong to user).

    If the recording has a session_id, also return audio_filenames from session_utterances
    and a pending_reprocessing flag (stale if recording was created before session ended).
    """
    async with pool.acquire() as conn:
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
            return None
        result = dict(row)

        # Staleness check: recording was created before session ended
        # (session reset for reprocessing but recording not yet regenerated)
        session_status = result.pop("session_status", None)
        session_ended_at = result.pop("session_ended_at", None)
        result["pending_reprocessing"] = (
            session_status == "ended"
            and session_ended_at is not None
            and result.get("created_at") is not None
            and result["created_at"] < session_ended_at
        )

        # Attach audio_filenames derived from speaker_segments (not created_at timestamps).
        # The segments carry audio_filename references from the transcription service,
        # which is more reliable than session_utterances.created_at as a timeline marker.
        if result.get("session_id"):
            segments = result.get("speaker_segments", [])
            # json columns are returned as strings by asyncpg — parse if needed
            if segments and isinstance(segments, str):
                import json
                segments = json.loads(segments)
            if segments and isinstance(segments, list):
                seen, audio_filenames = set(), []
                for seg in segments:
                    fn = seg.get("audio_filename") if isinstance(seg, dict) else seg.get("audio_filename")  # noqa: RUF034
                    if fn and fn not in seen:
                        seen.add(fn)
                        audio_filenames.append(fn)
                if audio_filenames:
                    result["audio_filenames"] = audio_filenames
                    result.pop("speaker_segments", None)
                    return result
            # Fallback: use audio_range to filter session_utterances
            audio_range_start = result.get("audio_range_start")
            audio_range_end = result.get("audio_range_end")
            if audio_range_start and audio_range_end:
                audio_rows = await conn.fetch(
                    """
                    SELECT audio_filename
                    FROM session_utterances
                    WHERE session_id = $1
                      AND created_at > $2 AT TIME ZONE 'UTC' - INTERVAL '2 minutes'
                      AND created_at < $3 AT TIME ZONE 'UTC' + INTERVAL '2 minutes'
                    ORDER BY created_at
                    """,
                    result["session_id"],
                    audio_range_start,
                    audio_range_end,
                )
                result["audio_filenames"] = [r["audio_filename"] for r in audio_rows if r["audio_filename"]]
            else:
                audio_rows = await conn.fetch(
                    """
                    SELECT audio_filename
                    FROM session_utterances
                    WHERE session_id = $1
                    ORDER BY created_at
                    """,
                    result["session_id"],
                )
                result["audio_filenames"] = [r["audio_filename"] for r in audio_rows if r["audio_filename"]]
        else:
            # Legacy: single audio_filename
            result["audio_filenames"] = (
                [result["audio_filename"]] if result.get("audio_filename") else []
            )
        # Remove speaker_segments from response to avoid leaking large data
        result.pop("speaker_segments", None)
        return result


async def delete_recording(user_id: int, recording_id: int) -> bool:
    """Delete a recording. Returns True if deleted."""
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM recordings WHERE id = $1 AND user_id = $2",
            recording_id,
            user_id,
        )
        return result == "DELETE 1"


async def get_active_session_recording(user_id: int) -> dict | None:
    """Build a recording-like dict from the active session's utterances.

    Returns None if no active session or no utterances yet.
    With deferred transcription, transcripts are empty until batch reprocessing.
    """
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            """
            SELECT id, user_id, started_at
            FROM sessions
            WHERE user_id = $1 AND status = 'active'
            ORDER BY started_at DESC LIMIT 1
            """,
            user_id,
        )
        if not session:
            return None

        # Get all utterances in chronological order (including deferred ones)
        utterances = await conn.fetch(
            """
            SELECT utterance_id, audio_filename, transcript, named_segments, created_at
            FROM session_utterances
            WHERE session_id = $1
            ORDER BY created_at
            """,
            session["id"],
        )
        if not utterances:
            return None

        # Merge transcripts and speakers across all utterances
        import json as _json
        all_segments = []
        all_named = []
        for utt in utterances:
            transcript = utt["transcript"]
            if isinstance(transcript, str):
                transcript = _json.loads(transcript)
            all_segments.extend(transcript.get("segments", []))

            named = utt["named_segments"]
            if isinstance(named, str):
                named = _json.loads(named)
            all_named.extend(named)

        audio_files = [utt["audio_filename"] for utt in utterances if utt["audio_filename"]]

        return {
            "id": f"active-{session['id']}",
            "session_id": session["id"],
            "timestamp": session["started_at"],
            "transcript": {"segments": all_segments},
            "speakers": all_named,
            "summary": None,
            "todos": [],
            "calendar": [],
            "notes": [],
            "conversation_changes": [],
            "audio_filename": audio_files[0] if audio_files else None,
            "audio_filenames": audio_files,
            "is_live": True,
        }


async def get_unknown_speakers(user_id: int) -> list[dict]:
    """Get recordings containing unresolved raw or Unknown speaker labels."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, speakers, audio_filename, speaker_segments
            FROM recordings
            WHERE user_id = $1
              AND (speakers::text LIKE '%Unknown%' OR speakers::text LIKE '%SPEAKER_%')
            """,
            user_id,
        )
        return [dict(row) for row in rows]


async def get_all_recordings_with_speakers(user_id: int) -> list[dict]:
    """Get all recordings with their speakers column for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, speakers FROM recordings WHERE user_id = $1",
            user_id,
        )
        return [dict(row) for row in rows]


async def update_speaker_name(recording_id: int, old_name: str, new_name: str):
    """Update speaker name in a recording."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE recordings
            SET speakers = (
                SELECT jsonb_agg(
                    CASE
                        WHEN elem->>'name' = $1 THEN jsonb_set(elem, '{name}', $3::jsonb)
                        ELSE elem
                    END
                )
                FROM jsonb_array_elements(speakers) AS elem
            )
            WHERE id = $2
        """,
            old_name,
            recording_id,
            new_name,
        )


async def get_all_voiceprints(user_id: int) -> list[dict]:
    """Get all voiceprints for a user."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, embedding
            FROM voiceprints
            WHERE user_id = $1
        """,
            user_id,
        )
        return [dict(row) for row in rows]


async def save_voiceprint(user_id: int, name: str, embedding: bytes):
    """Save or update a voiceprint."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO voiceprints (user_id, name, embedding)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, name)
            DO UPDATE SET embedding = $3
        """,
            user_id,
            name,
            embedding,
        )


async def get_todos(user_id: int) -> list[dict]:
    """Get all todos for a user, ordered by creation date."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.task, t.owner, t.due, t.priority, t.completed,
                   t.completed_at, t.created_at, t.recording_id,
                   COALESCE(r.timestamp, t.created_at) AS recording_timestamp
            FROM todos t
            LEFT JOIN recordings r ON r.id = t.recording_id
            WHERE t.user_id = $1
            ORDER BY t.created_at ASC
            """,
            user_id,
        )
        return [dict(row) for row in rows]


async def get_todos_for_date(user_id: int, date: str) -> list[dict]:
    """Get todos from recordings on a specific date (YYYY-MM-DD, Eastern Time)."""
    from datetime import date as _date

    parts = date.split("-")
    query_date = _date(int(parts[0]), int(parts[1]), int(parts[2]))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.id, t.task, t.owner, t.due, t.priority, t.completed,
                   t.completed_at, t.created_at, t.recording_id,
                   COALESCE(r.timestamp, t.created_at) AS recording_timestamp
            FROM todos t
            LEFT JOIN recordings r ON r.id = t.recording_id
            WHERE t.user_id = $1
              AND (t.recording_id IS NULL OR
                   DATE(r.timestamp AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = $2)
            ORDER BY t.created_at ASC
            """,
            user_id,
            query_date,
        )
        return [dict(row) for row in rows]


async def get_todos_for_recording(recording_id: int) -> list[dict]:
    """Get all todos for a specific recording."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, task, owner, due, priority, completed, completed_at, created_at
            FROM todos WHERE recording_id = $1
            ORDER BY created_at ASC
            """,
            recording_id,
        )
        return [dict(row) for row in rows]


async def save_todos(recording_id: int, user_id: int, todos: list[dict]):
    """Insert todos for a recording. Called only on first processing."""
    async with pool.acquire() as conn:
        for todo in todos:
            await conn.execute(
                """
                INSERT INTO todos (user_id, recording_id, task, owner, due, priority)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                user_id,
                recording_id,
                todo["task"],
                todo.get("owner") or "Unassigned",
                todo.get("due"),
                todo.get("priority", "medium"),
            )


async def create_todo(
    user_id: int, task: str, owner: str, due: str | None, priority: str, recording_id: int | None
) -> int:
    """Create a single todo. recording_id is None for standalone todos."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO todos (user_id, recording_id, task, owner, due, priority)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            user_id, recording_id, task, owner, due, priority,
        )
        return row["id"]


async def update_todo_completion(todo_id: int, completed: bool):
    """Mark a todo as completed or incomplete."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE todos
            SET completed = $1, completed_at = CASE WHEN $1 THEN NOW() ELSE NULL END
            WHERE id = $2
            """,
            completed,
            todo_id,
        )


async def delete_todo(todo_id: int):
    """Delete a todo."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM todos WHERE id = $1", todo_id)


async def get_todo_owner(todo_id: int) -> int | None:
    """Get the user_id that owns a todo. Returns None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM todos WHERE id = $1", todo_id
        )
        return row["user_id"] if row else None


async def save_decisions(recording_id: int, user_id: int, decisions: list[dict]):
    """Insert decisions for a recording. Always overwrites existing decisions."""
    async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM decisions WHERE recording_id = $1", recording_id
            )
            for d in decisions:
                await conn.execute(
                    """INSERT INTO decisions (user_id, recording_id, decision, made_by, context, reason)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    user_id,
                    recording_id,
                    d["decision"],
                    d.get("made_by") or "Unknown",
                    d.get("context"),
                    d.get("reason"),
                )


async def create_decision(
    user_id: int, decision: str, made_by: str, context: str | None, reason: str | None, recording_id: int | None
) -> int:
    """Create a single decision. recording_id is None for standalone decisions."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO decisions (user_id, recording_id, decision, made_by, context, reason)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            user_id, recording_id, decision, made_by, context, reason,
        )
        return row["id"]


async def get_decisions(
    user_id: int, limit: int = 50, include_archived: bool = False
) -> list[dict]:
    """Get recent decisions across all recordings."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT d.id, d.decision, d.made_by, d.context, d.reason,
                   d.archived, d.created_at, d.recording_id,
                   COALESCE(r.timestamp, d.created_at) AS recording_timestamp
            FROM decisions d
            LEFT JOIN recordings r ON r.id = d.recording_id
            WHERE d.user_id = $1
              AND ($2 OR d.archived = FALSE)
            ORDER BY d.created_at DESC
            LIMIT $3
            """,
            user_id,
            include_archived,
            limit,
        )
        return [dict(row) for row in rows]


async def get_decisions_for_recording(recording_id: int) -> list[dict]:
    """Get all decisions for a specific recording."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, decision, made_by, context, reason, archived, created_at
            FROM decisions WHERE recording_id = $1
            ORDER BY created_at ASC
            """,
            recording_id,
        )
        return [dict(row) for row in rows]


async def update_decision_archive(decision_id: int, archived: bool) -> None:
    """Update the archived status of a decision."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE decisions SET archived = $1 WHERE id = $2", archived, decision_id
        )


async def delete_decision(decision_id: int) -> None:
    """Delete a decision."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM decisions WHERE id = $1", decision_id)


async def get_decision_owner(decision_id: int) -> int | None:
    """Get the user_id that owns a decision. Returns None if not found."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM decisions WHERE id = $1", decision_id
        )
        return row["user_id"] if row else None


async def save_utterance_chunk(
    user_id: int,
    utterance_id: int,
    chunk_index: int,
    audio_bytes: bytes,
    is_final: bool,
) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO utterance_chunks
               (user_id, utterance_id, chunk_index, audio_bytes, is_final)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (user_id, utterance_id, chunk_index)
               DO UPDATE SET audio_bytes = $4, is_final = $5
               RETURNING id""",
            user_id,
            utterance_id,
            chunk_index,
            audio_bytes,
            is_final,
        )
        return row["id"]


async def get_utterance_chunks(user_id: int, utterance_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT chunk_index, audio_bytes, is_final
               FROM utterance_chunks
               WHERE user_id = $1 AND utterance_id = $2
               ORDER BY chunk_index""",
            user_id,
            utterance_id,
        )
        return [dict(row) for row in rows]


async def delete_utterance_chunks(user_id: int, utterance_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM utterance_chunks WHERE user_id = $1 AND utterance_id = $2",
            user_id,
            utterance_id,
        )


async def update_recording_speakers(recording_id: int, speakers: list):
    """Update speakers for a recording after re-identification."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE recordings
            SET speakers = $1::jsonb
            WHERE id = $2
        """,
            speakers,
            recording_id,
        )
async def update_recording_speaker_data(
    recording_id: int, speakers: list, speaker_segments: list
) -> None:
    """Update speaker labels and encrypted segment metadata together."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE recordings
            SET speakers = $2, speaker_segments = $3::jsonb
            WHERE id = $1
            """,
            recording_id,
            speakers,
            speaker_segments,
        )


async def update_recording_category(recording_id: int, category: str):
    """Update the category classification for a recording."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE recordings
            SET category = $1
            WHERE id = $2
        """,
            category,
            recording_id,
        )


# ── Session operations ─────────────────────────────────────────────


async def get_active_session(user_id: int) -> dict | None:
    """Fetch most recent session with status='active' for a user."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, started_at, ended_at, status, created_at
            FROM sessions
            WHERE user_id = $1 AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row else None


async def create_session(user_id: int, started_at: datetime) -> int:
    """Insert a new active session; return its id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sessions (user_id, started_at, status)
            VALUES ($1, $2, 'active')
            RETURNING id
            """,
            user_id,
            started_at.replace(tzinfo=None),
        )
        return row["id"]


async def end_session(session_id: int):
    """Mark a session as ended."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
            SET ended_at = NOW(), status = 'ended'
            WHERE id = $1
            """,
            session_id,
        )


async def get_idle_active_sessions(max_idle_minutes: float) -> list[dict]:
    """Find active sessions whose last activity is older than max_idle_minutes.

    Activity = latest session_utterance.created_at, or session.started_at if none.
    Returns session dicts ready for reprocessing.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.user_id, s.started_at, s.ended_at
            FROM sessions s
            WHERE s.status = 'active'
              AND (
                  SELECT COALESCE(MAX(su.created_at), s.started_at)
                  FROM session_utterances su
                  WHERE su.session_id = s.id
              ) < NOW() - make_interval(mins => $1)
            ORDER BY s.started_at
            """,
            max_idle_minutes,
        )
        return [dict(row) for row in rows]


async def mark_session_processed(session_id: int):
    """Mark a session as processed (after LLM summarization)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE sessions
            SET status = 'processed'
            WHERE id = $1
            """,
            session_id,
        )


async def reset_session_for_reprocessing(session_id: int) -> bool:
    """Reset a session so the hourly reprocess loop picks it up.

    Sets status back to 'ended'. The existing recording is kept but is now
    stale (its created_at < session.ended_at), which matches the hourly
    loop's staleness check in get_sessions_for_reprocessing().

    Returns True if a session was reset, False if session not found.
    """
    async with pool.acquire() as conn:
        # Verify session exists
        session = await conn.fetchrow(
            "SELECT id, status FROM sessions WHERE id = $1",
            session_id,
        )
        if not session:
            return False

        # Reset status to 'ended' so hourly loop picks it up
        # The recording stays but is stale (created_at < ended_at)
        await conn.execute(
            """
            UPDATE sessions
            SET status = 'ended'
            WHERE id = $1
            """,
            session_id,
        )

        logger.info("Session %d reset for reprocessing (was %s)", session_id, session["status"])
        return True


async def append_session_utterance(
    session_id: int,
    utterance_id: int,
    audio_filename: str,
    transcript: dict,
    named_segments: list,
    utterance_timestamp: datetime | None = None,
):
    """Store an utterance within a session.

    If utterance_timestamp is provided, it's used as created_at instead of NOW().
    This preserves the original timestamp from when the device sent the audio.
    """
    async with pool.acquire() as conn:
        if utterance_timestamp is not None:
            await conn.execute(
                """
                INSERT INTO session_utterances
                    (session_id, utterance_id, audio_filename, transcript,
                     named_segments, created_at)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                session_id,
                utterance_id,
                audio_filename,
                transcript,
                named_segments,
                utterance_timestamp.replace(tzinfo=None),
            )
        else:
            await conn.execute(
                """
                INSERT INTO session_utterances
                    (session_id, utterance_id, audio_filename, transcript,
                     named_segments)
                VALUES ($1, $2, $3, $4, $5)
                """,
                session_id,
                utterance_id,
                audio_filename,
                transcript,
                named_segments,
            )


async def update_session_utterance(
    session_id: int,
    utterance_id: int,
    transcript: dict,
    named_segments: list,
):
    """Update transcript and named_segments for a session utterance."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE session_utterances
            SET transcript = $3, named_segments = $4
            WHERE session_id = $1 AND utterance_id = $2
            """,
            session_id,
            utterance_id,
            transcript,
            named_segments,
        )


async def get_session_all_utterances(session_id: int) -> list[dict]:
    """Fetch all session_utterances, ordered by created_at."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT utterance_id, audio_filename, transcript, named_segments,
                   created_at
            FROM session_utterances
            WHERE session_id = $1
            ORDER BY created_at
            """,
            session_id,
        )
        return [dict(row) for row in rows]


async def get_last_utterance_time(session_id: int) -> datetime | None:
    """Get the created_at of the last utterance in a session."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT created_at
            FROM session_utterances
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            session_id,
        )
        return row["created_at"] if row else None


async def get_session_utterances_in_range(
    session_id: int, start_time: datetime, end_time: datetime
) -> list[dict]:
    """Fetch utterances in a session within a time range, ordered by created_at."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT utterance_id, audio_filename, transcript, named_segments,
                   created_at
            FROM session_utterances
            WHERE session_id = $1
              AND created_at >= $2
              AND created_at <= $3
            ORDER BY created_at
            """,
            session_id,
            start_time,
            end_time,
        )
        return [dict(row) for row in rows]


async def get_active_sessions_with_utterances() -> list[dict]:
    """Find active sessions that have at least one utterance."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT s.id, s.user_id, s.started_at, s.ended_at
            FROM sessions s
            JOIN session_utterances su ON su.session_id = s.id
            WHERE s.status = 'active'
            ORDER BY s.started_at
            """,
        )
        return [dict(row) for row in rows]


async def get_utterance_queue_entry(user_id: int, utterance_id: int) -> dict | None:
    """Fetch utterance queue entry to get its timestamp."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, utterance_id, status, created_at
            FROM utterance_queue
            WHERE user_id = $1 AND utterance_id = $2
            """,
            user_id,
            utterance_id,
        )
        return dict(row) if row else None
async def create_transcription_job(
    session_id: int,
    window_start: datetime,
    window_end: datetime,
    chunk_index: int,
    language: str = "auto",
) -> int:
    """Queue one full transcription job for a session window."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO transcription_jobs
                (session_id, window_start, window_end, chunk_index, status, stage, job_type, language)
            VALUES ($1, $2, $3, $4, 'pending', 'queued', 'full', $5)
            RETURNING id
            """,
            session_id,
            window_start.replace(tzinfo=None),
            window_end.replace(tzinfo=None),
            chunk_index,
            language,
        )
        return row["id"]
async def create_quick_transcription_job(
    session_id: int,
    audio_filename: str,
    utterance_id: int,
    created_at: datetime,
    language: str = "auto",
) -> int:
    """Queue an ASR-only job for one newly stored session utterance."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO transcription_jobs
                (session_id, window_start, window_end, chunk_index, status, stage,
                 job_type, result, language)
            VALUES ($1, $4, $4, $3, 'pending', 'queued', 'quick', $2::jsonb, $5)
            RETURNING id
            """,
            session_id,
            {"audio_filename": audio_filename, "utterance_id": utterance_id},
            utterance_id,
            created_at.replace(tzinfo=None),
            language,
        )
        return row["id"]


async def create_session_quick_job(
    session_id: int,
    utterance_ids: list[int],
    window_start: datetime,
    window_end: datetime,
    language: str = "auto",
) -> int:
    """Create one quick job covering all given utterances in a session (sliding window batch)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO transcription_jobs
                (session_id, window_start, window_end, chunk_index, status, stage,
                 job_type, result, language)
            VALUES ($1, $2, $3, 0, 'pending', 'queued', 'quick',
                    jsonb_build_object('session_id', $1::integer, 'utterance_ids', $4::jsonb), $5)
            RETURNING id
            """,
            session_id,
            window_start.replace(tzinfo=None),
            window_end.replace(tzinfo=None),
            utterance_ids,
            language,
        )
        return row["id"]


async def get_pending_session_quick_job(session_id: int) -> dict | None:
    """Return a pending quick job for the session, if one exists."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, window_start, window_end, chunk_index,
                   status, stage, job_type, result, created_at
            FROM transcription_jobs
            WHERE session_id = $1 AND job_type = 'quick' AND status = 'pending'
            LIMIT 1
            """,
            session_id,
        )
        return dict(row) if row else None



async def get_session_user_id(session_id: int) -> int | None:
    """Get the user_id for a session."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id FROM sessions WHERE id = $1",
            session_id,
        )
        return row["user_id"] if row else None

async def get_transcription_jobs(session_id: int) -> list[dict]:
    """Return all transcription jobs for a session in chunk order."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, window_start, window_end, chunk_index,
                   status, stage, job_type, result, error, failed_count,
                   created_at, started_at, completed_at
            FROM transcription_jobs
            WHERE session_id = $1
            ORDER BY chunk_index NULLS LAST, id
            """,
            session_id,
        )
        return [dict(row) for row in rows]


async def claim_transcription_job() -> dict | None:
    """Atomically claim one pending transcription job."""
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            """
            SELECT id, session_id, window_start, window_end, chunk_index,
                   status, stage, job_type, result, error, failed_count,
                   created_at, started_at, completed_at
            FROM transcription_jobs
            WHERE status = 'pending'
            ORDER BY created_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        )
        if not row:
            return None
        await conn.execute(
            "UPDATE transcription_jobs SET status = 'processing', started_at = NOW() WHERE id = $1",
            row["id"],
        )
        claimed = dict(row)
        claimed["status"] = "processing"
        return claimed


async def get_transcription_job(job_id: int) -> dict | None:
    """Fetch one transcription job."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, session_id, window_start, window_end, chunk_index,
                   status, stage, job_type, result, error, failed_count,
                   created_at, started_at, completed_at
            FROM transcription_jobs WHERE id = $1
            """,
            job_id,
        )
        return dict(row) if row else None


async def update_job_stage(job_id: int, stage: str) -> None:
    """Persist worker progress for a claimed job."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE transcription_jobs SET stage = $2 WHERE id = $1",
            job_id,
            stage,
        )


async def complete_transcription_job(job_id: int, result: dict) -> None:
    """Persist a completed transcription result."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET result = $2::jsonb, status = 'done', stage = 'done', completed_at = NOW()
            WHERE id = $1
            """,
            job_id,
            result,
        )


async def fail_transcription_job(job_id: int, error: str) -> None:
    """Retry a failed job at most twice; leave the third failure terminal."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET failed_count = failed_count + 1,
                error = $2,
                status = CASE WHEN failed_count + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                stage = CASE WHEN failed_count + 1 >= 3 THEN 'failed' ELSE 'queued' END,
                completed_at = CASE WHEN failed_count + 1 >= 3 THEN NOW() ELSE NULL END
            WHERE id = $1
            """,
            job_id,
            error,
        )


async def get_completed_quick_jobs() -> list[dict]:
    """Return completed quick jobs whose result is not yet applied."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, session_id, chunk_index, result, completed_at
            FROM transcription_jobs
            WHERE job_type = 'quick' AND status = 'done'
              AND COALESCE((result->>'applied')::boolean, false) = false
            ORDER BY completed_at, id
            """
        )
        return [dict(row) for row in rows]


async def mark_quick_job_applied(job_id: int) -> None:
    """Mark one completed quick result as consumed."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE transcription_jobs
            SET result = jsonb_set(COALESCE(result, '{}'::jsonb), '{applied}', 'true'::jsonb)
            WHERE id = $1 AND job_type = 'quick' AND status = 'done'
            """,
            job_id,
        )


async def update_session_utterance_transcript(
    session_id: int, utterance_id: int, transcript: dict
) -> None:
    """Update only the transcript JSON for one session utterance."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE session_utterances SET transcript = $3::jsonb
            WHERE session_id = $1 AND utterance_id = $2
            """,
            session_id,
            utterance_id,
            transcript,
        )


async def get_speaker_segments_for_recording(recording_id: int) -> list[dict]:
    """Return persisted speaker segments, tolerating legacy null values."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT speaker_segments FROM recordings WHERE id = $1",
            recording_id,
        )
        if not row:
            return []
        segments = row.get("speaker_segments")
        if isinstance(segments, str):
            import json
            segments = json.loads(segments)
        return segments if isinstance(segments, list) else []


async def save_session_recording(
    user_id: int,
    session_id: int,
    transcript: dict,
    speakers: list,
    result: dict,
    audio_filename: str,
    session_timestamp: datetime | None = None,
    category: str | None = None,
    speaker_segments: list | None = None,
    audio_range_start: datetime | None = None,
    audio_range_end: datetime | None = None,
) -> int:
    """Create or update a recording linked to a session."""
    ts = session_timestamp.replace(tzinfo=None) if session_timestamp else None
    stored_segments = speaker_segments or []
    # Derive audio range from segments if not provided
    if audio_range_start is None and stored_segments:
        try:
            first = stored_segments[0]
            start_offset = float(first.get("start", 0))
            if ts is not None:
                from datetime import timedelta
                audio_range_start = ts + timedelta(seconds=start_offset)
        except (ValueError, TypeError):
            pass
    if audio_range_end is None and stored_segments:
        try:
            last = stored_segments[-1]
            end_offset = float(last.get("end", 0))
            if ts is not None:
                from datetime import timedelta
                audio_range_end = ts + timedelta(seconds=end_offset)
        except (ValueError, TypeError):
            pass
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM recordings WHERE session_id = $1", session_id
        )
        if existing:
            if ts is not None:
                await conn.execute(
                    """
                    UPDATE recordings
                    SET transcript = $1, speakers = $2, summary = $3, todos = $4,
                        calendar = $5, notes = $6, conversation_changes = $7,
                        audio_filename = $8, speaker_segments = $9::json, timestamp = $10,
                        category = $11, audio_range_start = $13, audio_range_end = $14
                    WHERE id = $12
                    """,
                    transcript, speakers, result["summary"], result["todos"],
                    result["calendar"], result["notes"],
                    result.get("conversation_changes", []), audio_filename,
                    stored_segments, ts, category, existing["id"],
                    audio_range_start, audio_range_end,
                )
            else:
                await conn.execute(
                    """
                    UPDATE recordings
                    SET transcript = $1, speakers = $2, summary = $3, todos = $4,
                        calendar = $5, notes = $6, conversation_changes = $7,
                        audio_filename = $8, speaker_segments = $9::json,
                        timestamp = NOW(), category = $10,
                        audio_range_start = $12, audio_range_end = $13
                    WHERE id = $11
                    """,
                    transcript, speakers, result["summary"], result["todos"],
                    result["calendar"], result["notes"],
                    result.get("conversation_changes", []), audio_filename,
                    stored_segments, category, existing["id"],
                    audio_range_start, audio_range_end,
                )
        if ts is not None:
            row = await conn.fetchrow(
                """
                INSERT INTO recordings
                    (user_id, session_id, timestamp, transcript, speakers,
                     summary, todos, calendar, notes, conversation_changes,
                     audio_filename, speaker_segments, category,
                     audio_range_start, audio_range_end)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::json, $13, $14, $15)
                RETURNING id
                """,
                user_id, session_id, ts, transcript, speakers, result["summary"],
                result["todos"], result["calendar"], result["notes"],
                result.get("conversation_changes", []), audio_filename,
                stored_segments, category, audio_range_start, audio_range_end,
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO recordings
                    (user_id, session_id, timestamp, transcript, speakers,
                     summary, todos, calendar, notes, conversation_changes,
                     audio_filename, speaker_segments, category,
                     audio_range_start, audio_range_end)
                VALUES ($1, $2, NOW(), $3, $4, $5, $6, $7, $8, $9, $10, $11::json, $12, $13, $14)
                RETURNING id
                """,
                user_id, session_id, transcript, speakers, result["summary"],
                result["todos"], result["calendar"], result["notes"],
                result.get("conversation_changes", []), audio_filename,
                stored_segments, category, audio_range_start, audio_range_end,
            )
        return row["id"]
async def save_partition_recording(
    user_id: int,
    session_id: int,
    partition_index: int,
    transcript: dict,
    speakers: list,
    result: dict,
    audio_filename: str,
    stored_segments: list,
    partition_start: datetime,
    partition_end: datetime,
    category: str | None = None,
) -> int:
    """Insert a new partition recording for an existing session (gap-split path).

    Does NOT update an existing recording — always inserts. partition_index
    must be >= 1 (partition 0 is created by save_session_recording).
    """
    import json

    stored_segments_json = json.dumps(stored_segments)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO recordings
                (user_id, session_id, partition_index, timestamp, transcript, speakers,
                 summary, todos, calendar, notes, conversation_changes,
                 audio_filename, speaker_segments, category,
                 audio_range_start, audio_range_end)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::json, $14,
                    $15, $16)
            RETURNING id
            """,
            user_id,
            session_id,
            partition_index,
            partition_start,
            transcript,
            speakers,
            result["summary"],
            result["todos"],
            result["calendar"],
            result["notes"],
            result.get("conversation_changes", []),
            audio_filename,
            stored_segments_json,
            category,
            partition_start,
            partition_end,
        )
        return row["id"]


async def get_sessions_for_reprocessing(user_id: int | None = None) -> list[dict]:
    """All sessions with status='ended' that have no recording or need update."""
    async with pool.acquire() as conn:
        if user_id is not None:
            rows = await conn.fetch(
                """
                SELECT s.id, s.user_id, s.started_at, s.ended_at
                FROM sessions s
                WHERE s.status = 'ended'
                  AND s.user_id = $1
                  AND (
                      NOT EXISTS (SELECT 1 FROM recordings r WHERE r.session_id = s.id)
                      OR EXISTS (
                          SELECT 1 FROM recordings r
                          WHERE r.session_id = s.id
                            AND r.created_at < s.ended_at
                      )
                  )
                ORDER BY s.started_at
                """,
                user_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT s.id, s.user_id, s.started_at, s.ended_at
                FROM sessions s
                WHERE s.status = 'ended'
                  AND (
                      NOT EXISTS (SELECT 1 FROM recordings r WHERE r.session_id = s.id)
                      OR EXISTS (
                          SELECT 1 FROM recordings r
                          WHERE r.session_id = s.id
                            AND r.created_at < s.ended_at
                      )
                  )
                ORDER BY s.started_at
                """
            )
        return [dict(row) for row in rows]


async def get_sessions_by_date_range(
    user_id: int, start: datetime, end: datetime
) -> list[dict]:
    """Fetch sessions in a time range."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, started_at, ended_at, status
            FROM sessions
            WHERE user_id = $1
              AND started_at >= $2
              AND started_at < $3
              AND status != 'active'
            ORDER BY started_at
            """,
            user_id,
            start.replace(tzinfo=None),
            end.replace(tzinfo=None),
        )
        return [dict(row) for row in rows]


async def join_sessions(session_ids: list[int], keep_id: int):
    """Merge multiple sessions into keep_id; delete the rest."""
    if not session_ids:
        return
    # Filter out keep_id from the list to delete
    delete_ids = [sid for sid in session_ids if sid != keep_id]
    if not delete_ids:
        return
    async with pool.acquire() as conn:
        # Move session_utterances from deleted sessions to kept session
        await conn.execute(
            """
            UPDATE session_utterances
            SET session_id = $1
            WHERE session_id = ANY($2)
            """,
            keep_id,
            delete_ids,
        )
        # Update kept session's ended_at to latest of merged sessions
        await conn.execute(
            """
            UPDATE sessions
            SET ended_at = (
                SELECT MAX(COALESCE(ended_at, started_at))
                FROM sessions
                WHERE id = ANY($1)
            )
            WHERE id = $2
            """,
            session_ids,
            keep_id,
        )
        # Delete the other sessions
        await conn.execute(
            "DELETE FROM sessions WHERE id = ANY($1)",
            delete_ids,
        )


async def get_recording_audio_filenames(session_id: int) -> list[str]:
    """Get all audio filenames for a session (for audio concatenation)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT audio_filename
            FROM session_utterances
            WHERE session_id = $1
            ORDER BY created_at
            """,
            session_id,
        )
        return [row["audio_filename"] for row in rows]


# ── Daily summaries ────────────────────────────────────────────────


async def save_daily_summary(user_id: int, date, summary: dict):
    """Insert or update a daily summary for a user and date."""
    from datetime import date as _date
    if isinstance(date, str):
        date_obj = _date.fromisoformat(date)
    else:
        date_obj = date
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO daily_summaries (user_id, date, summary)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, date) DO UPDATE SET summary = $3
            """,
            user_id,
            date_obj,
            summary,
        )


async def get_daily_summary(user_id: int, date_str: str) -> dict | None:
    """Get the daily summary for a user on a specific date (YYYY-MM-DD)."""
    from datetime import date as _date
    date_obj = _date.fromisoformat(date_str)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT summary
            FROM daily_summaries
            WHERE user_id = $1 AND date = $2
            """,
            user_id,
            date_obj,
        )
        return dict(row)["summary"] if row else None


async def get_users_with_sessions_previous_day() -> list[int]:
    """Get distinct user_ids that had sessions yesterday."""
    from datetime import timedelta
    now = datetime.now(UTC)
    yesterday = (now - timedelta(days=1)).date()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT user_id
            FROM sessions
            WHERE DATE(started_at AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') = $1
            """,
            yesterday,
        )
        return [r["user_id"] for r in rows]



# ── User settings ──────────────────────────────────────────────────


async def get_user_settings(user_id: int) -> dict:
    """Get user settings. Returns defaults if no row exists."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT language, llm_context FROM user_settings WHERE user_id = $1",
            user_id,
        )
        if row:
            return dict(row)
        return {"language": "auto", "llm_context": ""}


async def save_user_settings(user_id: int, language: str, llm_context: str) -> None:
    """Upsert user settings row."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_settings (user_id, language, llm_context, updated_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET language = EXCLUDED.language,
                    llm_context = EXCLUDED.llm_context,
                    updated_at = EXCLUDED.updated_at
            """,
            user_id, language, llm_context,
        )
