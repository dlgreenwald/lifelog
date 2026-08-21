import json
from datetime import UTC, datetime

import asyncpg

from lifelog.config import settings

# ── Pure helpers ───────────────────────────────────────────────────


def is_meaningful_speech(named_segments: list) -> bool:
    """Return True if the utterance has any transcribed text.

    Any segment with non-empty text means the chunk contains speech.
    Empty segments (silence, noise, untranscribed audio) are not meaningful.
    """
    if not named_segments:
        return False
    return any(seg.get("text", "").strip() for seg in named_segments)


# ── Global connection pool
pool: asyncpg.Pool = None


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
        ssl=False,
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
            "SELECT id, api_key, oidc_sub, name, encryption_secret FROM users WHERE api_key = $1",
            api_key,
        )
        return dict(row) if row else None


async def get_user_by_oidc_sub(oidc_sub: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, api_key, oidc_sub, name, encryption_secret FROM users WHERE oidc_sub = $1",
            oidc_sub,
        )
        return dict(row) if row else None


async def create_user(
    api_key: str | None = None, oidc_sub: str | None = None, name: str | None = None
) -> dict:
    import secrets

    encryption_secret = secrets.token_hex(32)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO users (api_key, oidc_sub, name, encryption_secret)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            api_key,
            oidc_sub,
            name,
            encryption_secret,
        )
        return {
            "id": row["id"],
            "api_key": api_key,
            "oidc_sub": oidc_sub,
            "name": name,
            "encryption_secret": encryption_secret,
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
            json.dumps(transcript),
            json.dumps(named_segments),
            result["summary"],
            json.dumps(result["todos"]),
            json.dumps(result["calendar"]),
            json.dumps(result["notes"]),
            json.dumps(result.get("conversation_changes", [])),
            audio_filename,
        )
        return row["id"]


async def get_recordings_by_date(user_id: int, date: str) -> list[dict]:
    """Get all recordings for a user on a specific date (YYYY-MM-DD)."""
    from datetime import date as _date
    date_obj = _date.fromisoformat(date)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, summary, todos, calendar, notes, speakers
            FROM recordings
            WHERE user_id = $1 AND DATE(timestamp) = $2
            ORDER BY timestamp DESC
        """,
            user_id,
            date_obj,
        )
        return [dict(row) for row in rows]


async def get_recording(user_id: int, recording_id: int) -> dict | None:
    """Get a specific recording (must belong to user).

    If the recording has a session_id, also return audio_filenames from session_utterances.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM recordings
            WHERE id = $1 AND user_id = $2
        """,
            recording_id,
            user_id,
        )
        if not row:
            return None
        result = dict(row)
        # Attach audio_filenames from session_utterances if session_id exists
        if result.get("session_id"):
            audio_rows = await conn.fetch(
                """
                SELECT audio_filename
                FROM session_utterances
                WHERE session_id = $1
                ORDER BY created_at
                """,
                result["session_id"],
            )
            result["audio_filenames"] = [r["audio_filename"] for r in audio_rows]
        else:
            # Legacy: single audio_filename
            result["audio_filenames"] = (
                [result["audio_filename"]] if result.get("audio_filename") else []
            )
        return result


async def get_unknown_speakers(user_id: int) -> list[dict]:
    """Get all recordings with unknown speakers for labeling."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, speakers, audio_filename
            FROM recordings
            WHERE user_id = $1
            AND speakers::text LIKE '%Unknown%'
        """,
            user_id,
        )
        return [dict(row) for row in rows]


async def update_speaker_name(recording_id: int, old_name: str, new_name: str):
    """Update speaker name in a recording."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE recordings
            SET speakers = jsonb_set(
                speakers,
                '{speakers}',
                (SELECT jsonb_agg(
                    CASE
                        WHEN elem->>'name' = $1 THEN jsonb_set(elem, '{name}', $3::jsonb)
                        ELSE elem
                    END
                ) FROM jsonb_array_elements(speakers) AS elem)
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
    """Get all open TODOs across all recordings."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, todos
            FROM recordings
            WHERE user_id = $1
            AND todos IS NOT NULL
            AND todos != '[]'::jsonb
            ORDER BY timestamp DESC
        """,
            user_id,
        )
        result = []
        for row in rows:
            todos = json.loads(row["todos"]) if isinstance(row["todos"], str) else row["todos"]
            for todo in todos:
                todo["recording_id"] = row["id"]
                todo["recording_timestamp"] = str(row["timestamp"])
                result.append(todo)
        return result


async def get_decisions(user_id: int, limit: int = 20) -> list[dict]:
    """Get recent decisions across all recordings."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, summary
            FROM recordings
            WHERE user_id = $1
            ORDER BY timestamp DESC
            LIMIT $2
        """,
            user_id,
            limit,
        )
        return [dict(row) for row in rows]


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
            json.dumps(speakers),
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


async def append_session_utterance(
    session_id: int,
    utterance_id: int,
    audio_filename: str,
    transcript: dict,
    named_segments: list,
    is_meaningful: bool,
):
    """Store an utterance within a session."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO session_utterances
                (session_id, utterance_id, audio_filename, transcript, named_segments, is_meaningful)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            session_id,
            utterance_id,
            audio_filename,
            json.dumps(transcript),
            json.dumps(named_segments),
            is_meaningful,
        )


async def get_session_meaningful_utterances(session_id: int) -> list[dict]:
    """Fetch session_utterances WHERE is_meaningful = TRUE, ordered by created_at."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT utterance_id, audio_filename, transcript, named_segments, created_at
            FROM session_utterances
            WHERE session_id = $1 AND is_meaningful = TRUE
            ORDER BY created_at
            """,
            session_id,
        )
        return [dict(row) for row in rows]


async def get_session_all_utterances(session_id: int) -> list[dict]:
    """Fetch all session_utterances (including non-meaningful), ordered by created_at."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT utterance_id, audio_filename, transcript, named_segments,
                   is_meaningful, created_at
            FROM session_utterances
            WHERE session_id = $1
            ORDER BY created_at
            """,
            session_id,
        )
        return [dict(row) for row in rows]


async def get_last_meaningful_utterance_time(session_id: int) -> datetime | None:
    """Get the created_at of the last meaningful utterance in a session."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT created_at
            FROM session_utterances
            WHERE session_id = $1 AND is_meaningful = TRUE
            ORDER BY created_at DESC
            LIMIT 1
            """,
            session_id,
        )
        return row["created_at"] if row else None


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


async def save_session_recording(
    user_id: int,
    session_id: int,
    transcript: dict,
    speakers: list,
    result: dict,
    audio_filename: str,
) -> int:
    """Create or update a recording linked to a session (UPSERT on session_id)."""
    async with pool.acquire() as conn:
        # Check if recording already exists for this session
        existing = await conn.fetchrow(
            "SELECT id FROM recordings WHERE session_id = $1",
            session_id,
        )
        if existing:
            await conn.execute(
                """
                UPDATE recordings
                SET transcript = $1, speakers = $2, summary = $3, todos = $4,
                    calendar = $5, notes = $6, conversation_changes = $7,
                    audio_filename = $8, timestamp = NOW()
                WHERE id = $9
                """,
                json.dumps(transcript),
                json.dumps(speakers),
                result["summary"],
                json.dumps(result["todos"]),
                json.dumps(result["calendar"]),
                json.dumps(result["notes"]),
                json.dumps(result.get("conversation_changes", [])),
                audio_filename,
                existing["id"],
            )
            return existing["id"]
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO recordings
                    (user_id, session_id, timestamp, transcript, speakers,
                     summary, todos, calendar, notes, conversation_changes, audio_filename)
                VALUES ($1, $2, NOW(), $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                user_id,
                session_id,
                json.dumps(transcript),
                json.dumps(speakers),
                result["summary"],
                json.dumps(result["todos"]),
                json.dumps(result["calendar"]),
                json.dumps(result["notes"]),
                json.dumps(result.get("conversation_changes", [])),
                audio_filename,
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
