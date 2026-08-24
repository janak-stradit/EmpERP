"""add close status to existing projects

Revision ID: 37096bb64c19
Revises: 5dfc69d69084
Create Date: 2026-08-24 12:52:35.093216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37096bb64c19'
down_revision: Union[str, Sequence[str], None] = '5dfc69d69084'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed a 'Close' (done-category) status at the end of every project's workflow
    that doesn't already have a status by that name."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO ticket_statuses (project_id, name, category, color, position, is_default, wip_limit)
            SELECT p.id, 'Close', 'DONE', '#495057',
                   COALESCE((SELECT MAX(ts.position) + 1 FROM ticket_statuses ts WHERE ts.project_id = p.id), 0),
                   false, NULL
            FROM projects p
            WHERE NOT EXISTS (
                SELECT 1 FROM ticket_statuses ts WHERE ts.project_id = p.id AND ts.name = 'Close'
            )
            """
        )
    )


def downgrade() -> None:
    """Remove the seeded 'Close' status from projects, but only where it has no tickets
    (a project that already used the name for something else, or has tickets filed
    against it, is left untouched)."""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM ticket_statuses ts
            WHERE ts.name = 'Close' AND ts.category = 'DONE'
              AND NOT EXISTS (SELECT 1 FROM tickets t WHERE t.status_id = ts.id)
            """
        )
    )
