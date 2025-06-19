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

from src.database import Base, User, KnownChat, Participant, Poll, WebApp, Response, PollSetting, PollOptionSetting

# revision identifiers, used by Alembic.
revision: str = 'sqlite_to_postgres'
down_revision: Union[str, None] = 'cd7dc4de4cc3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Migrate data from SQLite to PostgreSQL"""
    # Get the current connection
    connection = op.get_bind()
    
    # Create a session for SQLite
    sqlite_engine = sa.create_engine('sqlite:///poll_data.db')
    SQLiteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SQLiteSession()
    
    # The order matters due to foreign key constraints
    MODELS_IN_ORDER = [
        User, KnownChat, Participant, WebApp, Poll,
        Response, PollSetting, PollOptionSetting
    ]
    
    try:
        # Clear PostgreSQL database
        for model in reversed(MODELS_IN_ORDER):
            table_name = model.__tablename__
            connection.execute(text(f"DELETE FROM {table_name}"))
            
        # Migrate data
        for model in MODELS_IN_ORDER:
            table_name = model.__tablename__
            all_objects = sqlite_session.query(model).all()
            
            if all_objects:
                for obj in all_objects:
                    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
                    insert_sql = f"INSERT INTO {table_name} ({', '.join(data.keys())}) VALUES ({', '.join(['%s'] * len(data))})"
                    connection.execute(text(insert_sql), tuple(data.values()))
                    
        connection.commit()
        
    except Exception as e:
        connection.rollback()
        raise e
    finally:
        sqlite_session.close()


def downgrade() -> None:
    """Migrate data from PostgreSQL back to SQLite"""
    # Get the current connection
    connection = op.get_bind()
    
    # Create a session for SQLite
    sqlite_engine = sa.create_engine('sqlite:///poll_data.db')
    SQLiteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SQLiteSession()
    
    # The order matters due to foreign key constraints
    MODELS_IN_ORDER = [
        User, KnownChat, Participant, WebApp, Poll,
        Response, PollSetting, PollOptionSetting
    ]
    
    try:
        # Clear SQLite database
        for model in reversed(MODELS_IN_ORDER):
            table_name = model.__tablename__
            sqlite_session.query(model).delete()
            sqlite_session.commit()
            
        # Migrate data
        for model in MODELS_IN_ORDER:
            table_name = model.__tablename__
            result = connection.execute(text(f"SELECT * FROM {table_name}")).fetchall()
            
            if result:
                for row in result:
                    obj = model(**dict(zip(row._fields, row)))
                    sqlite_session.add(obj)
                    
        sqlite_session.commit()
        
    except Exception as e:
        sqlite_session.rollback()
        raise e
    finally:
        sqlite_session.close()
