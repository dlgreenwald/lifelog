"""Drop is_meaningful from session_utterances, add category to recordings.

Revision ID: 006
Revises: 005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("session_utterances", "is_meaningful")
    op.add_column(
        "recordings",
        sa.Column("category", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recordings", "category")
    op.add_column(
        "session_utterances",
        sa.Column("is_meaningful", sa.Boolean(), nullable=True),
    )
