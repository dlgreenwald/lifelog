"""Add session_processed_at column to sessions.

Used by the cleanup pipeline to determine when raw audio files
(.enc from session_utterances) are eligible for deletion 24h
after a session is fully processed.

Revision ID: 027
Revises: 026
Create Date: 2026-09-12
"""

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sessions ADD COLUMN session_processed_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN session_processed_at")
