"""merge heads for show_text_results

Revision ID: 44aee0960ac6
Revises: a6130b674a5d, add_show_text_results
Create Date: 2025-06-20 09:28:57.615694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '44aee0960ac6'
down_revision: Union[str, None] = ('a6130b674a5d', 'add_show_text_results')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
