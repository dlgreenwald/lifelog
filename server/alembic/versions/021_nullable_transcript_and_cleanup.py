"""Make transcript nullable and clear empty-segment utterances for sessions with
empty-segment quick job results so the worker can re-process them with correct
windowing.

Revision ID: 021
Revises: 020
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make transcript nullable so we can set empty rows to NULL (worker treats
    # NULL as untranscribed via  ``not u.get("transcript")``).
    op.alter_column(
        "session_utterances",
        "transcript",
        nullable=True,
    )
    # Clear utterances whose quick-job results produced empty segment arrays.
    # The worker will pick these up as untranscribed and create new jobs
    # with the corrected rolling window floor.
    op.execute(
        """
        UPDATE session_utterances
        SET transcript = NULL
        WHERE session_id IN (
            SELECT DISTINCT tj.session_id
            FROM transcription_jobs tj
            WHERE tj.job_type = 'quick'
              AND tj.status = 'done'
              AND (tj.result->>'applied')::boolean = true
        )
        AND jsonb_array_length(coalesce(transcript->'segments', '[]'::jsonb)) = 0
        ;
        """
    )
    # Reset applied=false so the worker will re-apply these jobs.
    # The worker re-applies done jobs where applied=false.
    op.execute(
        """
        UPDATE transcription_jobs
        SET result = result - 'applied'
        WHERE job_type = 'quick'
          AND status = 'done'
          AND (result->>'applied')::boolean = true
        ;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        -- Restore transcript = {} for rows that were cleared
        UPDATE session_utterances
        SET transcript = '{}'
        WHERE transcript IS NULL
          AND session_id IN (
              SELECT DISTINCT session_id FROM transcription_jobs
              WHERE job_type = 'quick' AND status = 'done'
          )
        ;
        """
    )
    op.alter_column(
        "session_utterances",
        "transcript",
        nullable=False,
    )
