"""Add is_self to speakers table — marks the speaker as the owning user for right-alignment in transcript."""

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE speakers ADD COLUMN is_self BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE speakers DROP COLUMN is_self")
