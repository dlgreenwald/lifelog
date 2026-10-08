"""Add timezone to user_settings — stores IANA timezone name per user for date bucketing."""

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_settings ADD COLUMN timezone TEXT NOT NULL DEFAULT 'America/New_York'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN timezone")
