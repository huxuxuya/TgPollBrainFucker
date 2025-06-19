"""SQLite to PostgreSQL migration

Revision ID: sqlite_to_postgres
Revises: cd7dc4de4cc3
Create Date: 2025-06-19 17:54:21.386367

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.database import Base, User, KnownChat, Participant, Poll, Response, PollSetting, PollOptionSetting

# revision identifiers, used by Alembic.
revision: str = 'sqlite_to_postgres'
down_revision: Union[str, None] = 'cd7dc4de4cc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """This migration is a one-off for local data transfer and is disabled for deployment."""
    pass


def downgrade() -> None:
    """This migration is a one-off for local data transfer and is disabled for deployment."""
    pass
