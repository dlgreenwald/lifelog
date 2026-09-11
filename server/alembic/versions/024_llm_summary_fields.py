"""LLM summary fields: title, long_summary, speaker_id on todos/decisions.

Revision ID: 024
Revises: 023
Create Date: 2026-09-11
"""
import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # recordings: title and long_summary
    op.add_column(
        "recordings",
        sa.Column("title", sa.Text(), nullable=True),
    )
    op.add_column(
        "recordings",
        sa.Column("long_summary", sa.Text(), nullable=True),
    )

    # todos: speaker_id FK
    op.add_column(
        "todos",
        sa.Column("speaker_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_todos_speaker",
        "todos",
        "speakers",
        ["speaker_id"],
        ["id"],
    )

    # decisions: speaker_id FK
    op.add_column(
        "decisions",
        sa.Column("speaker_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_decisions_speaker",
        "decisions",
        "speakers",
        ["speaker_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_decisions_speaker", "decisions", type_="foreignkey")
    op.drop_column("decisions", "speaker_id")

    op.drop_constraint("fk_todos_speaker", "todos", type_="foreignkey")
    op.drop_column("todos", "speaker_id")

    op.drop_column("recordings", "long_summary")
    op.drop_column("recordings", "title")
