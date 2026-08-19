#!/usr/bin/env python3
"""Connect to the database and print all conversation transcripts.

Reads from recordings (if present) and session_utterances.
Requires asyncpg:  pip install asyncpg   (or use the server venv).
"""

import asyncio
import json
import os

import asyncpg


def fmt_ts(start):
    """Format seconds offset as [MM:SS]."""
    if start is None:
        return ""
    m, s = divmod(int(start), 60)
    return f" [{m:02d}:{s:02d}]"


def print_segments(segments):
    """Print structured transcript segments."""
    if isinstance(segments, str):
        segments = json.loads(segments)
    if isinstance(segments, list):
        for seg in segments:
            speaker = seg.get("speaker", "?")
            text = seg.get("text", "")
            ts = fmt_ts(seg.get("start"))
            print(f"  {speaker}{ts}: {text}")
    elif isinstance(segments, dict) and "text" in segments:
        print(segments["text"])
    else:
        print(json.dumps(segments, indent=2))


async def main():
    conn = await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "lifelog"),
        user=os.getenv("POSTGRES_USER", "lifelog"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )

    # ── Recordings (legacy path) ───────────────────────────────────
    recordings = await conn.fetch(
        """
        SELECT r.id, r.created_at, r.summary, r.transcript
        FROM recordings r
        ORDER BY r.created_at
        """
    )

    if recordings:
        print(f"\n{'#'*70}")
        print(f"#  RECORDINGS ({len(recordings)})")
        print(f"{'#'*70}")
        for row in recordings:
            ts = row["created_at"].strftime("%Y-%m-%d %H:%M:%S") if row["created_at"] else "?"
            print(f"\n{'='*70}")
            print(f"Recording {row['id']}  |  {ts}")
            print(f"{'='*70}")
            if row["summary"]:
                print(f"\nSummary: {row['summary']}\n")
            if row["transcript"]:
                print_segments(row["transcript"])
            else:
                print("  (no transcript)")

    # ── Sessions ────────────────────────────────────────────────────
    sessions = await conn.fetch(
        """
        SELECT s.id, s.user_id, s.started_at, s.ended_at, s.status
        FROM sessions s
        ORDER BY s.started_at
        """
    )

    if not sessions:
        if not recordings:
            print("No recordings or sessions found.")
        await conn.close()
        return

    print(f"\n{'#'*70}")
    print(f"#  SESSIONS ({len(sessions)})")
    print(f"{'#'*70}")

    for sess in sessions:
        started = sess["started_at"].strftime("%Y-%m-%d %H:%M:%S") if sess["started_at"] else "?"
        ended = sess["ended_at"].strftime("%H:%M:%S") if sess["ended_at"] else "ongoing"
        status = sess["status"]

        utts = await conn.fetch(
            """
            SELECT transcript, named_segments, is_meaningful, created_at
            FROM session_utterances
            WHERE session_id = $1
            ORDER BY created_at
            """,
            sess["id"],
        )

        print(f"\n{'='*70}")
        print(f"Session {sess['id']}  |  user={sess['user_id']}  |  {started} → {ended}  |  {status}")
        print(f"  Utterances: {len(utts)}")
        print(f"{'='*70}")

        for u in utts:
            label = "" if u["is_meaningful"] else " [not meaningful]"
            segments = u["named_segments"] or u["transcript"]
            if segments:
                print_segments(segments)
            if label:
                print(f"  ({label.strip()})")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
