"""Speakers table with 1-many voiceprints.

Revision ID: 023
Revises: 022
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "speakers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_speakers_user_name"),
    )

    # Backfill speakers from distinct (user_id, name) voiceprints.
    op.execute(
        "INSERT INTO speakers (user_id, name, created_at) "
        "SELECT DISTINCT user_id, name, now() FROM voiceprints"
    )

    op.add_column(
        "voiceprints",
        sa.Column("speaker_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_voiceprints_speaker",
        "voiceprints",
        "speakers",
        ["speaker_id"],
        ["id"],
    )
    op.execute(
        "UPDATE voiceprints vp SET speaker_id = s.id "
        "FROM speakers s WHERE s.user_id = vp.user_id AND s.name = vp.name"
    )
    op.alter_column("voiceprints", "speaker_id", nullable=False)

    op.drop_constraint("uq_voiceprints_user_name", "voiceprints")
    op.drop_column("voiceprints", "name")
    op.drop_column("voiceprints", "user_id")

    op.create_index("idx_voiceprints_speaker", "voiceprints", ["speaker_id"])


def downgrade() -> None:
    op.drop_index("idx_voiceprints_speaker", "voiceprints")
    op.add_column("voiceprints", sa.Column("name", sa.Text(), nullable=True))
    op.add_column("voiceprints", sa.Column("user_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE voiceprints vp SET name = s.name, user_id = s.user_id "
        "FROM speakers s WHERE s.id = vp.speaker_id"
    )
    op.alter_column("voiceprints", "name", nullable=False)
    op.alter_column("voiceprints", "user_id", nullable=False)
    op.create_unique_constraint("uq_voiceprints_user_name", "voiceprints", ["user_id", "name"])
    op.drop_column("voiceprints", "speaker_id")
    op.drop_table("speakers")
