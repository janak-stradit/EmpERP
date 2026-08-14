"""merge multiple heads

Revision ID: fce62df7f76b
Revises: 4a8f96334969, c1a4f9d3e8b2
Create Date: 2026-08-12 11:34:38.970765

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fce62df7f76b'
down_revision: Union[str, Sequence[str], None] = ('4a8f96334969', 'c1a4f9d3e8b2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
