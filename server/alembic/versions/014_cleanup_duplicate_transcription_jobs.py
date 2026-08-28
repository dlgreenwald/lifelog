"""Remove duplicate transcription jobs from hourly reprocess overscheduling.

Keeps the most recent job per (session_id, chunk_index). Removes older duplicates
and any stuck/failed jobs that were part of the overscheduling loop.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Delete all but the newest job per (session_id, chunk_index).
    # This removes the duplicated chunks from the overscheduling bug.
    # Idempotent: re-running is safe (no duplicates left = nothing deleted).
    op.execute(
        """
        DELETE FROM transcription_jobs
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM transcription_jobs
            GROUP BY session_id, chunk_index
        )
        """
    )


def downgrade() -> None:
    # Cannot recover deleted rows; no-op.
    pass
