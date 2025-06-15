import logging
import os
from sqlalchemy import create_engine, inspect, text

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_database_url():
    """Gets the database URL from environment variables, matching the main app."""
    db_url = os.environ.get('DATABASE_URL', 'sqlite:///poll_data.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    logging.info(f"Using database connection: {db_url}")
    return db_url

def run_migrations():
    """
    Performs all necessary database migrations using SQLAlchemy.
    This script is idempotent and safe to run multiple times.
    """
    try:
        engine = create_engine(get_database_url())
        inspector = inspect(engine)

        # --- Migration 1: Add 'type' column to 'known_chats' ---
        logging.info("--- Checking migration for 'known_chats' table ---")
        known_chats_columns = [col['name'] for col in inspector.get_columns('known_chats')]
        
        if 'type' not in known_chats_columns:
            logging.info("Column 'type' not found in 'known_chats'. Adding it...")
            with engine.connect() as connection:
                connection.execute(text("ALTER TABLE known_chats ADD COLUMN type TEXT"))
                connection.commit()
            logging.info("Successfully added 'type' column to 'known_chats'.")
        else:
            logging.info("Column 'type' in 'known_chats' already exists. Skipping.")

        # --- Migration 2: Add 'poll_type' column to 'polls' ---
        logging.info("--- Checking migration for 'polls' table ---")
        polls_columns = [col['name'] for col in inspector.get_columns('polls')]

        if 'poll_type' not in polls_columns:
            logging.info("Column 'poll_type' not found in 'polls'. Adding it with default value...")
            with engine.connect() as connection:
                # Default 'native' is crucial for existing rows so the column can be NOT NULL.
                stmt = text("ALTER TABLE polls ADD COLUMN poll_type TEXT NOT NULL DEFAULT 'native'")
                connection.execute(stmt)
                connection.commit()
            logging.info("Successfully added 'poll_type' column to 'polls'.")
        else:
            logging.info("Column 'poll_type' in 'polls' already exists. Skipping.")

    except Exception as e:
        logging.error(f"An error occurred during the ORM migration: {e}")
        logging.error("Please ensure the database is accessible and all tables exist.")

if __name__ == "__main__":
    logging.info("Starting ORM-based database migration...")
    run_migrations()
    logging.info("Migration script finished.") 