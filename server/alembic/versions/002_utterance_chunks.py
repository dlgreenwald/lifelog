"""Add utterance_chunks table for chunked audio uploads.

Revision ID: 002
Revises: 001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "utterance_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("utterance_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("audio_bytes", sa.LargeBinary(), nullable=False),
        sa.Column(
            "is_final",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(), server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "user_id",
            "utterance_id",
            "chunk_index",
            name="uq_utterance_chunks_user_utt_idx",
        ),
    )
    op.create_index(
        "idx_utterance_chunks_lookup",
        "utterance_chunks",
        ["user_id", "utterance_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_utterance_chunks_lookup", table_name="utterance_chunks")
    op.drop_table("utterance_chunks")
