"""Add utterance_id to recordings and create utterance_queue table.

Revision ID: 003
Revises: 002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add utterance_id to recordings (nullable for backwards compat)
    op.add_column(
        "recordings",
        sa.Column("utterance_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "idx_recordings_user_utterance",
        "recordings",
        ["user_id", "utterance_id"],
    )

    # Create utterance_queue table
    op.create_table(
        "utterance_queue",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("utterance_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),  # pending, processing, done, failed
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(), server_default=sa.func.now()),
        sa.Column("started_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "utterance_id",
            name="uq_utterance_queue_user_utt",
        ),
    )
    op.create_index(
        "idx_utterance_queue_status",
        "utterance_queue",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("idx_utterance_queue_status", table_name="utterance_queue")
    op.drop_table("utterance_queue")
    op.drop_index("idx_recordings_user_utterance", table_name="recordings")
    op.drop_column("recordings", "utterance_id")
