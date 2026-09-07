"""Add recorded_at to utterance_queue.

Records the device's wall-clock timestamp when provided, allowing correct
session placement and calendar display for offline batch uploads.

Revision ID: 023
Revises: 022
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "utterance_queue",
        sa.Column("recorded_at", sa.TIMESTAMP(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("utterance_queue", "recorded_at")
