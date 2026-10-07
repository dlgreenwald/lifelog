"""Add offline and processed_at to sessions.

offline (bool, default false): distinguishes offline batch sessions from
  live recording sessions. Offline sessions store recordings with their original
  backdated recorded_at timestamps; live sessions use server time.

processed_at (timestamp, nullable): set by mark_offline_session_processed()
  after the worker fires transcription jobs so the session is not re-selected
  on the next poll cycle.

Revision ID: 028
Revises: 027
Create Date: 2026-09-13
"""

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sessions ADD COLUMN offline BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE sessions ADD COLUMN processed_at TIMESTAMP"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sessions DROP COLUMN processed_at")
    op.execute("ALTER TABLE sessions DROP COLUMN offline")
