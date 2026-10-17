"""Add notes TEXT column to recordings."""

from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'notes'
            ) THEN
                ALTER TABLE recordings ADD COLUMN notes TEXT NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE recordings DROP COLUMN IF EXISTS notes")
