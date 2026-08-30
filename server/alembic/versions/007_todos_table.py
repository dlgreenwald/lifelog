"""Create todos table with stable IDs and migrate existing JSONB data.

Revision ID: 007
Revises: 006
"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "todos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "recording_id",
            sa.Integer(),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False, server_default="Unassigned"),
        sa.Column("due", sa.Text(), nullable=True),
        sa.Column(
            "priority",
            sa.Text(),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("idx_todos_user_id", "todos", ["user_id"])
    op.create_index("idx_todos_recording_id", "todos", ["recording_id"])
    op.create_index("idx_todos_created_at", "todos", ["created_at"])

    # Migrate existing JSONB todos from recordings.todos into the new table
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, user_id, todos FROM recordings "
            "WHERE todos IS NOT NULL AND todos != '[]'::jsonb"
        )
    ).fetchall()
    for row in rows:
        recording_id = row[0]
        user_id = row[1]
        todos_raw = row[2]
        todos = json.loads(todos_raw) if isinstance(todos_raw, str) else todos_raw
        for todo in todos:
            conn.execute(
                sa.text(
                    "INSERT INTO todos (user_id, recording_id, task, owner, due, priority) "
                    "VALUES (:user_id, :recording_id, :task, :owner, :due, :priority)"
                ),
                {
                    "user_id": user_id,
                    "recording_id": recording_id,
                    "task": todo["task"],
                    "owner": todo.get("owner") or "Unassigned",
                    "due": todo.get("due"),
                    "priority": todo.get("priority", "medium"),
                },
            )


def downgrade() -> None:
    op.drop_index("idx_todos_created_at", table_name="todos")
    op.drop_index("idx_todos_recording_id", table_name="todos")
    op.drop_index("idx_todos_user_id", table_name="todos")
    op.drop_table("todos")
