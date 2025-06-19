'''deduplicate participants and enforce composite primary key

Revision ID: 3e7b4f9c2a9d
Revises: cd7dc4de4cc3
Create Date: 2025-06-20 00:44:30.000000
'''
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '3e7b4f9c2a9d'
# use latest existing revision id as parent
down_revision: Union[str, None] = 'cd7dc4de4cc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _delete_duplicates_sqlite(conn):
    conn.execute(text("""
        DELETE FROM participants
        WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM participants
            GROUP BY chat_id, user_id
        );
    """))


def _delete_duplicates_generic(conn):
    # Works for Postgres, MySQL 8+, etc.
    conn.execute(text("""
        WITH ranked AS (
            SELECT ctid AS rid,
                   ROW_NUMBER() OVER (PARTITION BY chat_id, user_id) AS rn
            FROM participants
        )
        DELETE FROM participants p USING ranked r
        WHERE p.ctid = r.rid AND r.rn > 1;
    """))


def _ensure_pk(conn):
    inspector = sa.inspect(conn)
    pk = inspector.get_pk_constraint('participants')
    # If PK already correct, nothing to do
    expected_cols = {'chat_id', 'user_id'}
    if pk and set(pk.get('constrained_columns', [])) == expected_cols:
        return
    # Drop existing PK/unique that conflicts
    if pk and pk['name']:
        op.drop_constraint(pk['name'], 'participants', type_='primary')
    # Create new composite PK
    op.create_primary_key('pk_participants', 'participants', ['chat_id', 'user_id'])


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == 'sqlite':
        _delete_duplicates_sqlite(bind)
        # SQLite can't ALTER TABLE to add PK; create unique index instead
        op.create_index('ux_participants_chat_user', 'participants', ['chat_id', 'user_id'], unique=True)
    else:
        _delete_duplicates_generic(bind)
        _ensure_pk(bind)


def downgrade() -> None:
    # Downgrade simply drops the PK we added (if any). Data loss from duplicate
    # deletions is irreversible, so we don't attempt to restore it.
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        op.drop_index('ux_participants_chat_user', table_name='participants')
    else:
        inspector = sa.inspect(bind)
        pk = inspector.get_pk_constraint('participants')
        if pk and pk['name'] == 'pk_participants':
            op.drop_constraint('pk_participants', 'participants', type_='primary')
