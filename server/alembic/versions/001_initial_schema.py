"""Initial schema — users, recordings, voiceprints

Revision ID: 001
Revises:
Create Date: 2026-08-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("api_key", sa.Text(), unique=True, nullable=True),
        sa.Column("oidc_sub", sa.Text(), unique=True, nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("encryption_secret", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
    )

    # --- recordings ---
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("timestamp", sa.TIMESTAMP(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(), nullable=True),
        sa.Column("speakers", postgresql.JSONB(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("todos", postgresql.JSONB(), nullable=True),
        sa.Column("calendar", postgresql.JSONB(), nullable=True),
        sa.Column("notes", postgresql.JSONB(), nullable=True),
        sa.Column("conversation_changes", postgresql.JSONB(), nullable=True),
        sa.Column("audio_filename", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_recordings_user_timestamp",
        "recordings",
        ["user_id", "timestamp"],
    )

    # --- voiceprints ---
    op.create_table(
        "voiceprints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "name", name="uq_voiceprints_user_name"),
    )
    op.create_index(
        "idx_voiceprints_user",
        "voiceprints",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_voiceprints_user", table_name="voiceprints")
    op.drop_table("voiceprints")
    op.drop_index("idx_recordings_user_timestamp", table_name="recordings")
    op.drop_table("recordings")
    op.drop_table("users")
