"""add sprint_projects link table

Revision ID: 5dfc69d69084
Revises: 7774c1dea7eb
Create Date: 2026-08-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5dfc69d69084'
down_revision: Union[str, Sequence[str], None] = '7774c1dea7eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('sprint_projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sprint_id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['sprint_id'], ['sprints.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sprint_id', 'project_id', name='uq_sprint_project')
    )
    op.create_index(op.f('ix_sprint_projects_sprint_id'), 'sprint_projects', ['sprint_id'], unique=False)
    op.create_index(op.f('ix_sprint_projects_project_id'), 'sprint_projects', ['project_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_sprint_projects_project_id'), table_name='sprint_projects')
    op.drop_index(op.f('ix_sprint_projects_sprint_id'), table_name='sprint_projects')
    op.drop_table('sprint_projects')
