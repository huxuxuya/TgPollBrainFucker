"""merge heads

Revision ID: a6130b674a5d
Revises: 3e7b4f9c2a9d, sqlite_to_postgres
Create Date: 2025-06-20 00:50:50.958206

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6130b674a5d'
down_revision: Union[str, None] = ('3e7b4f9c2a9d', 'sqlite_to_postgres')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
