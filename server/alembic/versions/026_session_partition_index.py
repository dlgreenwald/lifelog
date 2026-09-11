"""Fix session-level partition_index collision: use -1 for session summaries.

Session-level recordings (save_session_recording) and partition recordings
(save_partition_recording) both used partition_index=0, violating the
(session_id, partition_index) unique constraint.

Fix: session-level recordings use partition_index=-1 (outside the >=0 range
covered by the unique index), while real partitions use 0+.
save_partition_recording uses ON CONFLICT DO UPDATE for idempotency.

Revision ID: 026
Revises: 024
Create Date: 2026-09-11
"""

from alembic import op

revision = "026"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old partial index if it exists
    op.execute("DROP INDEX IF EXISTS recordings_session_partition_idx")
    # Create simple unique index: (session_id, partition_index) where both are NOT NULL.
    # partition_index=-1 for session-level rows cannot collide with partition rows (0+).
    # Each session has exactly one session-level row (partition_index=-1) and
    # N partition rows (partition_index=0,1,2...N-1), so uniqueness is guaranteed.
    op.execute(
        """
        CREATE UNIQUE INDEX recordings_session_partition_idx
        ON recordings (session_id, partition_index)
        WHERE session_id IS NOT NULL AND partition_index IS NOT NULL
        """
    )
    # Backfill: recordings that have session_id but were the only recording
    # for that session (i.e., true session-level summaries with no partitions)
    # get partition_index=-1. Sessions with multiple recordings had their
    # first recording incorrectly set to partition_index=0 by the old code.
    op.execute(
        """
        UPDATE recordings
        SET partition_index = -1
        WHERE session_id IS NOT NULL
          AND partition_index = 0
          AND (
              SELECT COUNT(*) FROM recordings r2
              WHERE r2.session_id = recordings.session_id
          ) = 1
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS recordings_session_partition_idx")
    # Restore original partial index (session_id IS NOT NULL only)
    op.execute(
        """
        CREATE UNIQUE INDEX recordings_session_partition_idx
        ON recordings (session_id, partition_index)
        WHERE session_id IS NOT NULL
        """
    )
    # Restore partition_index=0 for session-level rows
    op.execute(
        """
        UPDATE recordings
        SET partition_index = 0
        WHERE session_id IS NOT NULL AND partition_index = -1
        """
    )
