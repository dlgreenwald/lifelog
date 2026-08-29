"""Add language column to transcription_jobs table."""

from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE transcription_jobs ADD COLUMN language TEXT NOT NULL DEFAULT 'auto'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE transcription_jobs DROP COLUMN language")
