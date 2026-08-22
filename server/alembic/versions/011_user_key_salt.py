"""Add random per-user encryption salt.

Revision ID: 011
Revises: 010
"""
import secrets
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("key_salt", sa.LargeBinary(), nullable=True))

    # Backfill existing users with random salts (Python-side to avoid pgcrypto dependency)
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM users")).fetchall()
    for row in rows:
        salt = secrets.token_bytes(16)
        conn.execute(
            sa.text("UPDATE users SET key_salt = :salt WHERE id = :id"),
            {"salt": salt, "id": row[0]},
        )

    op.alter_column("users", "key_salt", nullable=False)


def downgrade() -> None:
    op.drop_column("users", "key_salt")
