"""add must_change_password to users

Revision ID: c1a4f9d3e8b2
Revises: b1417e9065fd
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a4f9d3e8b2'
down_revision: Union[str, Sequence[str], None] = 'b1417e9065fd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'users',
        sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('users', 'must_change_password', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'must_change_password')
