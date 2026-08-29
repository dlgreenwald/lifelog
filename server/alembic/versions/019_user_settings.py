"""Add user_settings table for language and llm_context preferences."""

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE user_settings ("
        "    user_id INTEGER PRIMARY KEY REFERENCES users(id),"
        "    language TEXT NOT NULL DEFAULT 'auto',"
        "    llm_context TEXT NOT NULL DEFAULT '',"
        "    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP TABLE user_settings")
