"""Create decisions table with stable IDs for archive/delete support.

Revision ID: 009
Revises: 007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "recording_id",
            sa.Integer(),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("made_by", sa.Text(), nullable=False, server_default="Unknown"),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_decisions_user_id", "decisions", ["user_id"])
    op.create_index("idx_decisions_recording_id", "decisions", ["recording_id"])
    op.create_index("idx_decisions_created_at", "decisions", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_decisions_created_at", table_name="decisions")
    op.drop_index("idx_decisions_recording_id", table_name="decisions")
    op.drop_index("idx_decisions_user_id", table_name="decisions")
    op.drop_table("decisions")
