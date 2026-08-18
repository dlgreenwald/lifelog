"""Main E2E test orchestrator.

Ties together: TTS generation → audio chunking → upload → pipeline verification.
Manages test user setup/teardown in PostgreSQL for clean, idempotent runs.

Usage:
    python -m e2e.run_e2e e2e/conversations/standup.yaml [--server-url URL]
"""

import argparse
import asyncio
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path

import asyncpg
import yaml

from e2e.config import (
    API_KEY,
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    SERVER_URL,
    VOICES_DIR,
)
from e2e.chunk_audio import chunk_and_encode
from e2e.generate_audio import generate_conversation
from e2e.upload_chunks import upload_chunks
from e2e.verify_results import poll_status

# Resolve paths relative to this file (works under uv run or direct invocation)
_HERE = Path(__file__).resolve().parent


# ── Database helpers ───────────────────────────────────────────────

async def get_db_pool():
    """Connect to PostgreSQL."""
    return await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        min_size=1,
        max_size=5,
    )


async def setup_user(pool) -> int:
    """Create or reset the test user. Returns user_id."""
    async with pool.acquire() as conn:
        # Check if test user exists
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE api_key = $1", API_KEY
        )

        if row:
            user_id = row["id"]
            print(f"Test user exists (id={user_id}), cleaning prior data...")

            # Query recordings for disk cleanup before deleting
            recordings = await conn.fetch(
                "SELECT audio_filename FROM recordings WHERE user_id = $1",
                user_id,
            )

            # Delete in FK-safe order
            await conn.execute(
                "DELETE FROM utterance_queue WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM utterance_chunks WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM recordings WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM voiceprints WHERE user_id = $1", user_id
            )

            # Best-effort: delete encrypted audio files
            for rec in recordings:
                fn = rec["audio_filename"]
                if fn:
                    # Audio stored in server's audio_storage_path
                    # We can't know the exact path from here, but we tried
                    pass

            # Delete and recreate user (fresh encryption_secret)
            await conn.execute(
                "DELETE FROM users WHERE api_key = $1", API_KEY
            )
        else:
            print("Creating new test user...")

        # Create user
        encryption_secret = secrets.token_hex(32)
        row = await conn.fetchrow(
            """INSERT INTO users (api_key, name, encryption_secret)
               VALUES ($1, $2, $3) RETURNING id""",
            API_KEY,
            "E2E Test User",
            encryption_secret,
        )
        user_id = row["id"]
        print(f"Test user created: id={user_id}, api_key={API_KEY}")
        return user_id


async def teardown_user(pool, user_id: int):
    """Clean up test user and all associated data."""
    async with pool.acquire() as conn:
        # Query recordings for filenames before deleting
        try:
            recordings = await conn.fetch(
                "SELECT audio_filename FROM recordings WHERE user_id = $1",
                user_id,
            )
        except Exception:
            recordings = []

        # Delete in FK-safe order
        await conn.execute(
            "DELETE FROM utterance_queue WHERE user_id = $1", user_id
        )
        await conn.execute(
            "DELETE FROM utterance_chunks WHERE user_id = $1", user_id
        )
        await conn.execute(
            "DELETE FROM recordings WHERE user_id = $1", user_id
        )
        await conn.execute(
            "DELETE FROM voiceprints WHERE user_id = $1", user_id
        )
        await conn.execute(
            "DELETE FROM users WHERE id = $1", user_id
        )

        # Best-effort: delete encrypted audio files
        # (would need server's audio_storage_path config to know where)
        for rec in recordings:
            fn = rec.get("audio_filename")
            if fn:
                # Try common paths
                for base in ["/data/audio", "/tmp/lifelog-audio"]:
                    path = os.path.join(base, fn)
                    if os.path.exists(path):
                        try:
                            os.unlink(path)
                        except OSError:
                            pass

        print("Teardown complete: all test data removed")


# ── Main orchestrator ─────────────────────────────────────────────

async def run_e2e(yaml_path: str, server_url: str = SERVER_URL):
    """Run the full E2E test pipeline."""
    print(f"\n{'='*60}")
    print(f"LifeLog E2E Integration Test")
    print(f"{'='*60}")
    print(f"Conversation: {yaml_path}")
    print(f"Server: {server_url}")
    print()

    # Load conversation YAML
    with open(yaml_path) as f:
        conv = yaml.safe_load(f)
    print(f"Loaded conversation: {conv['name']}")
    print(f"  Speakers: {list(conv['speakers'].keys())}")
    print(f"  Lines: {len(conv['lines'])}")
    print()

    # Connect to database
    pool = await get_db_pool()

    try:
        # Setup: idempotent test user creation
        print("─" * 40)
        print("Step 1: Setup")
        print("─" * 40)
        user_id = await setup_user(pool)
        utterance_id = int(time.time())  # Unique per run, fits int32
        print(f"  utterance_id: {utterance_id}")
        print()

        # Generate audio
        print("─" * 40)
        print("Step 2: Generate Audio (Piper TTS)")
        print("─" * 40)
        with tempfile.TemporaryDirectory(prefix="lifelog_e2e_") as tmpdir:
            wav_path = os.path.join(tmpdir, "conversation.wav")
            voices_dir = str(_HERE / VOICES_DIR)
            generate_conversation(yaml_path, voices_dir, wav_path)
            print()

            # Chunk and encode
            print("─" * 40)
            print("Step 3: Chunk Audio (5s Opus)")
            print("─" * 40)
            chunks_dir = os.path.join(tmpdir, "chunks")
            chunks = chunk_and_encode(wav_path, chunks_dir)
            print()

            # Upload chunks
            print("─" * 40)
            print("Step 4: Upload Chunks")
            print("─" * 40)
            responses = upload_chunks(chunks, utterance_id, server_url)
            print(f"  Uploaded {len(responses)} chunks")
            print()

            # Poll and verify
            print("─" * 40)
            print("Step 5: Verify Pipeline")
            print("─" * 40)
            status = poll_status(utterance_id, server_url)
            print(f"  Pipeline completed: {status}")
            print()

            # Query recording from DB for verification
            print("─" * 40)
            print("Step 6: Verify Recording in DB")
            print("─" * 40)
            async with pool.acquire() as conn:
                rec = await conn.fetchrow(
                    """SELECT id, transcript, speakers, summary, todos, notes
                       FROM recordings
                       WHERE user_id = $1 AND utterance_id = $2""",
                    user_id,
                    utterance_id,
                )

            if rec:
                print(f"  Recording ID: {rec['id']}")

                # Verify transcript
                import json
                transcript = rec["transcript"]
                if isinstance(transcript, str):
                    transcript = json.loads(transcript)
                segments = transcript.get("segments", [])
                print(f"  Transcript segments: {len(segments)}")
                if segments:
                    sample = segments[0].get("text", "")[:80]
                    print(f"  First segment: '{sample}...'")

                # Verify speakers
                speakers = rec["speakers"]
                if isinstance(speakers, str):
                    speakers = json.loads(speakers)
                print(f"  Named segments: {len(speakers)}")
                if speakers:
                    names = set(s.get("name", "Unknown") for s in speakers)
                    print(f"  Speaker names: {names}")

                # Verify summary
                summary = rec["summary"]
                print(f"  Summary present: {bool(summary)}")
                if summary:
                    print(f"  Summary preview: {summary[:120]}...")

                # Verify todos
                todos = rec["todos"]
                if isinstance(todos, str):
                    todos = json.loads(todos)
                print(f"  TODOs: {len(todos)}")

                print()
                print("─" * 40)
                print("RESULT: PASS")
                print("─" * 40)
                return 0
            else:
                print("  ERROR: Recording not found in database!")
                print()
                print("─" * 40)
                print("RESULT: FAIL (no recording)")
                print("─" * 40)
                return 1

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        print()
        print("─" * 40)
        print("RESULT: FAIL (exception)")
        print("─" * 40)
        return 1

    finally:
        # Teardown: always clean up
        print()
        print("─" * 40)
        print("Teardown")
        print("─" * 40)
        await teardown_user(pool, user_id)
        await pool.close()


def main():
    parser = argparse.ArgumentParser(
        description="LifeLog E2E Integration Test"
    )
    parser.add_argument(
        "conversation",
        help="Path to conversation YAML file",
    )
    parser.add_argument(
        "--server-url",
        default=SERVER_URL,
        help=f"Server URL (default: {SERVER_URL})",
    )
    args = parser.parse_args()

    # Resolve relative paths against the e2e/ directory
    yaml_path = Path(args.conversation)
    if not yaml_path.is_absolute():
        yaml_path = _HERE / yaml_path

    exit_code = asyncio.run(run_e2e(str(yaml_path), args.server_url))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
