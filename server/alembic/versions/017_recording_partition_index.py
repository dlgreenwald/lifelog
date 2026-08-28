"""Add partition_index to recordings for gap-split support.

Multiple recordings can now share a session_id (one per partition).
partition_index=0 is the first/primary recording.
New partitions created by gap-splitting have partition_index=1, 2, etc.
"""
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add partition_index column with default 0
    op.execute("ALTER TABLE recordings ADD COLUMN partition_index INTEGER NOT NULL DEFAULT 0")
    # Add unique constraint so (session_id, partition_index) is unique
    # Partial index to only enforce for rows where session_id is set
    op.execute(
        """
        CREATE UNIQUE INDEX recordings_session_partition_idx
        ON recordings (session_id, partition_index)
        WHERE session_id IS NOT NULL
        """
    )
    # Backfill partition_index=0 for existing recordings (default already set)
    # No-op since default is already 0


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS recordings_session_partition_idx")
    op.execute("ALTER TABLE recordings DROP COLUMN partition_index")
