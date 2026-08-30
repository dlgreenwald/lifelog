"""Add sessions and session_utterances tables, link recordings to sessions.

Revision ID: 004
Revises: 003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- sessions ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="active",
        ),  # active | ended | processed
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_sessions_user_time",
        "sessions",
        ["user_id", "started_at"],
    )
    op.create_index(
        "idx_sessions_user_status",
        "sessions",
        ["user_id", "status"],
    )

    # --- session_utterances ---
    op.create_table(
        "session_utterances",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column("utterance_id", sa.Integer(), nullable=False),
        sa.Column("audio_filename", sa.Text(), nullable=False),
        sa.Column("transcript", postgresql.JSONB(), nullable=False),
        sa.Column("named_segments", postgresql.JSONB(), nullable=False),
        sa.Column(
            "is_meaningful",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_session_utterances_session",
        "session_utterances",
        ["session_id"],
    )

    # --- recordings: add session_id ---
    op.add_column(
        "recordings",
        sa.Column(
            "session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=True
        ),
    )
    op.create_index(
        "idx_recordings_session",
        "recordings",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_recordings_session", table_name="recordings")
    op.drop_column("recordings", "session_id")
    op.drop_index("idx_session_utterances_session", table_name="session_utterances")
    op.drop_table("session_utterances")
    op.drop_index("idx_sessions_user_status", table_name="sessions")
    op.drop_index("idx_sessions_user_time", table_name="sessions")
    op.drop_table("sessions")
