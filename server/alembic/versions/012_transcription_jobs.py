"""Add transcription_jobs table for async transcription pipeline.

Revision ID: 012
Revises: 011
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcription_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("window_start", sa.TIMESTAMP(), nullable=False),
        sa.Column("window_end", sa.TIMESTAMP(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("stage", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
    )
    op.create_index("idx_tj_status", "transcription_jobs", ["status"])
    op.create_index("idx_tj_session", "transcription_jobs", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_tj_session", table_name="transcription_jobs")
    op.drop_index("idx_tj_status", table_name="transcription_jobs")
    op.drop_table("transcription_jobs")
