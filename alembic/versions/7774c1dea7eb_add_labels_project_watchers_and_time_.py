"""add labels, project watchers, and time tracking

Revision ID: 7774c1dea7eb
Revises: bc9a9f23edb6
Create Date: 2026-08-20 21:17:37.263110

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7774c1dea7eb'
down_revision: Union[str, Sequence[str], None] = 'bc9a9f23edb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('labels',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('color', sa.String(length=7), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'name', name='uq_label_project_name')
    )
    op.create_index(op.f('ix_labels_project_id'), 'labels', ['project_id'], unique=False)

    op.create_table('ticket_labels',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('label_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['label_id'], ['labels.id'], ),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ticket_id', 'label_id', name='uq_ticket_label')
    )
    op.create_index(op.f('ix_ticket_labels_label_id'), 'ticket_labels', ['label_id'], unique=False)
    op.create_index(op.f('ix_ticket_labels_ticket_id'), 'ticket_labels', ['ticket_id'], unique=False)

    op.create_table('work_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ticket_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('minutes_spent', sa.Integer(), nullable=False),
    sa.Column('log_date', sa.Date(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_logs_author_id'), 'work_logs', ['author_id'], unique=False)
    op.create_index(op.f('ix_work_logs_ticket_id'), 'work_logs', ['ticket_id'], unique=False)

    op.create_table('project_watchers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'employee_id', name='uq_project_watcher')
    )
    op.create_index(op.f('ix_project_watchers_employee_id'), 'project_watchers', ['employee_id'], unique=False)
    op.create_index(op.f('ix_project_watchers_project_id'), 'project_watchers', ['project_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_project_watchers_project_id'), table_name='project_watchers')
    op.drop_index(op.f('ix_project_watchers_employee_id'), table_name='project_watchers')
    op.drop_table('project_watchers')

    op.drop_index(op.f('ix_work_logs_ticket_id'), table_name='work_logs')
    op.drop_index(op.f('ix_work_logs_author_id'), table_name='work_logs')
    op.drop_table('work_logs')

    op.drop_index(op.f('ix_ticket_labels_ticket_id'), table_name='ticket_labels')
    op.drop_index(op.f('ix_ticket_labels_label_id'), table_name='ticket_labels')
    op.drop_table('ticket_labels')

    op.drop_index(op.f('ix_labels_project_id'), table_name='labels')
    op.drop_table('labels')
