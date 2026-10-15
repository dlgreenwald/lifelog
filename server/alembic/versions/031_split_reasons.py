"""Add split_reason_before and split_reason_after to recordings."""

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE recordings ADD COLUMN split_reason_before TEXT NULL"
    )
    op.execute(
        "ALTER TABLE recordings ADD COLUMN split_reason_after TEXT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP COLUMN split_reason_before")
    op.execute("ALTER TABLE recordings DROP COLUMN split_reason_after")
