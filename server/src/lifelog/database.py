import json
from datetime import UTC, datetime

import asyncpg

from lifelog.config import settings

# Global connection pool
pool: asyncpg.Pool = None


async def init_db():
    """Initialize PostgreSQL connection pool and run migrations."""
    global pool
    pool = await asyncpg.create_pool(
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        min_size=5,
        max_size=20,
        ssl="require",
    )

    # Run Alembic migrations to bring schema up to date
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

    print("[DB] Migrations applied successfully")


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
            datetime.now(tz=UTC),
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
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, timestamp, summary, todos, calendar, notes, speakers
            FROM recordings
            WHERE user_id = $1 AND DATE(timestamp) = $2
            ORDER BY timestamp DESC
        """,
            user_id,
            date,
        )
        return [dict(row) for row in rows]


async def get_recording(user_id: int, recording_id: int) -> dict | None:
    """Get a specific recording (must belong to user)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM recordings
            WHERE id = $1 AND user_id = $2
        """,
            recording_id,
            user_id,
        )
        return dict(row) if row else None


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
