"""Add job_type column to transcription_jobs for quick vs full transcription.

'full' = default, existing behavior (transcribe + align + diarize).
'quick' = ASR-only at upload time for near-real-time display.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "transcription_jobs",
        sa.Column("job_type", sa.Text(), server_default="full", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("transcription_jobs", "job_type")
