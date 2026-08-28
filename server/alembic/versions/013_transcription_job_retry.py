"""Add failed_count to transcription_jobs for retry tracking.

Prevents infinite requeue loops when jobs fail persistently (e.g. CUDA OOM).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE transcription_jobs
        ADD COLUMN IF NOT EXISTS failed_count INTEGER NOT NULL DEFAULT 0
        """
    )


def downgrade() -> None:
    op.drop_column("transcription_jobs", "failed_count")
