"""Add audio_range_start and audio_range_end to recordings.

These columns track the absolute time boundaries of each partition's
audio within the session, so the dashboard knows which audio files
to load for a gap-split recording partition.
"""
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE recordings ADD COLUMN audio_range_start TIMESTAMP WITHOUT TIME ZONE"
    )
    op.execute(
        "ALTER TABLE recordings ADD COLUMN audio_range_end TIMESTAMP WITHOUT TIME ZONE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP COLUMN audio_range_start")
    op.execute("ALTER TABLE recordings DROP COLUMN audio_range_end")
