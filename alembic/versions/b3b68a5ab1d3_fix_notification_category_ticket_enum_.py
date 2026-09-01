"""fix notification_category ticket enum value case

Revision ID: b3b68a5ab1d3
Revises: 76ef783ac758
Create Date: 2026-09-01 16:09:03.663584

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3b68a5ab1d3'
down_revision: Union[str, Sequence[str], None] = '76ef783ac758'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # e5afe19a9667 added 'ticket' (lowercase) to notification_category, but every
    # other value in this enum is uppercase (matching the Python enum's .name, which
    # is what SQLAlchemy binds for a plain Enum column). That mismatch made every
    # NotificationCategory.TICKET insert fail with InvalidTextRepresentation — no
    # ticket notification has ever been successfully written.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notification_category RENAME VALUE 'ticket' TO 'TICKET'")


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notification_category RENAME VALUE 'TICKET' TO 'ticket'")
