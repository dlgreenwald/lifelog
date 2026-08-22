"""Make recording_id nullable on todos and decisions for standalone items.

Revision ID: 010
Revises: 009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "todos",
        "recording_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "decisions",
        "recording_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "decisions",
        "recording_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "todos",
        "recording_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
