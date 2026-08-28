"""Add speaker_segments JSONB column to recordings.

Stores grouped speaker segments with per-segment audio after diarization.
Each segment: {speaker, start, end, text, audio_filename}.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recordings",
        sa.Column("speaker_segments", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("recordings", "speaker_segments")
