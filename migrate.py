import os
import time
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, Integer, BigInteger
from sqlalchemy.orm import sessionmaker

# It's crucial to load the environment variables before importing db models
load_dotenv()

# We need to import the models from our application's database module
# Assuming the script is run from the root directory.
from src.database import Base, User, KnownChat, Participant, Poll, WebApp, Response, PollSetting, PollOptionSetting

def migrate_data():
    """
    Migrates all data from a local SQLite database to the PostgreSQL database
    defined in the DATABASE_URL environment variable.
    This will ERASE ALL DATA in the destination (PostgreSQL) database first.
    """
    SQLITE_DB_PATH = 'sqlite:///poll_data.db'
    POSTGRES_URL = os.environ.get('DATABASE_URL')

    if not os.path.exists('poll_data.db'):
        print("!! ERROR: Local database file 'poll_data.db' not found. Aborting.")
        return
        
    if not POSTGRES_URL or not POSTGRES_URL.startswith('postgres'):
        print("!! ERROR: DATABASE_URL environment variable is not set or is not a PostgreSQL URL. Aborting migration.")
        print("   Make sure your .env file is configured correctly.")
        return

    print(f"Source (SQLite):      {SQLITE_DB_PATH}")
    print(f"Destination (Postgres): {POSTGRES_URL}")
    print("\n! WARNING: This script will completely WIPE all data in the destination database.")
    print("!          It is recommended to create a backup of your Postgres database first.")

    print("\n!!! MIGRATION WILL START IN 5 SECONDS. PRESS CTRL+C TO CANCEL !!!")
    time.sleep(5)

    # --- Setup database connections ---
    try:
        # Source (SQLite)
        sqlite_engine = create_engine(SQLITE_DB_PATH)
        SQLiteSession = sessionmaker(bind=sqlite_engine)
        sqlite_session = SQLiteSession()
        print("-> Connected to SQLite.")

        # Destination (PostgreSQL)
        pg_url = POSTGRES_URL
        if pg_url.startswith('postgres://'):
            pg_url = pg_url.replace('postgres://', 'postgresql://', 1)

        pg_engine = create_engine(pg_url)
        PGSession = sessionmaker(bind=pg_engine)
        pg_session = PGSession()
        print("-> Connected to PostgreSQL.")

    except Exception as e:
        print(f"!! FATAL: Could not connect to databases. Error: {e}")
        return

    # --- Migration Logic ---
    # The order matters due to foreign key constraints.
    # We delete in reverse order of creation and insert in order of creation.
    MODELS_IN_ORDER = [
        User, KnownChat, Participant, WebApp, Poll,
        Response, PollSetting, PollOptionSetting
    ]

    try:
        print("\n--- Step 1: Clearing destination database ---")
        for model in reversed(MODELS_IN_ORDER):
            table_name = model.__tablename__
            print(f"  - Deleting all rows from '{table_name}'...")
            num_deleted = pg_session.query(model).delete(synchronize_session=False)
            print(f"    {num_deleted} rows deleted.")
        pg_session.commit()
        print("-> Destination database cleared successfully.")

        print("\n--- Step 2: Migrating data from source to destination ---")
        for model in MODELS_IN_ORDER:
            table_name = model.__tablename__
            print(f"  - Migrating table '{table_name}'...")

            all_objects = sqlite_session.query(model).all()
            if not all_objects:
                print("    No data to migrate. Skipping.")
                continue
            
            print(f"    Found {len(all_objects)} objects to migrate.")

            for obj in all_objects:
                # By converting the object to a dict of its data and creating a new instance,
                # we detach it from the source session and can safely add it to the destination.
                data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
                new_obj = model(**data)
                pg_session.merge(new_obj)
            
        pg_session.commit()
        print("-> Data migrated successfully.")
        
        # --- Reset sequences for primary keys in Postgres ---
        print("\n--- Step 3: Resetting primary key sequences in PostgreSQL ---")
        for model in MODELS_IN_ORDER:
            table_name = model.__tablename__
            # Find the first primary key column that is an integer and auto-increments
            pk_cols = [c for c in model.__table__.primary_key.columns if isinstance(c.type, (Integer, BigInteger)) and c.autoincrement]
            if not pk_cols:
                continue
            
            pk_col_name = pk_cols[0].name
            
            try:
                # This query finds the sequence name automatically and sets it to the max current value
                sql_query = text(f"SELECT setval(pg_get_serial_sequence('{table_name}', '{pk_col_name}'), COALESCE((SELECT MAX({pk_col_name})+1 FROM {table_name}), 1), false);")
                pg_session.execute(sql_query)
                print(f"  - Sequence for '{table_name}.{pk_col_name}' reset.")
            except Exception as seq_e:
                print(f"  - WARNING: Could not reset sequence for '{table_name}'. This might be okay. Error: {seq_e}")
                pg_session.rollback()

        pg_session.commit()
        print("-> Sequences reset.")
        print("\n\n✅ Migration complete! All data has been successfully transferred.")

    except Exception as e:
        print(f"\n!! ERROR: An error occurred during migration: {e}")
        print("   -> Rolling back PostgreSQL transaction.")
        pg_session.rollback()
    finally:
        sqlite_session.close()
        pg_session.close()
        print("\n--- All database connections closed. ---")

if __name__ == '__main__':
    migrate_data()