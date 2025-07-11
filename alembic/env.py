from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line reads the sqlalchemy.url from the alembic.ini file
# and sets it for the context.
import os
import sys
from dotenv import load_dotenv

# --- Setup for project imports ---
# Add the project's root directory to the Python path
# This allows Alembic to find the 'src' module
project_root = os.path.realpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path=dotenv_path)

# --- Import models ---
from src.database import Base # noqa

# Correctly set the sqlalchemy.url from environment variables
# This replaces the %(DATABASE_URL)s placeholder from alembic.ini
# Fallback to a local SQLite DB if DATABASE_URL is not set.
db_url = os.environ.get('DATABASE_URL', 'sqlite:///poll_data.db')

if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)
config.set_main_option('sqlalchemy.url', db_url)


# If a logger is configured in alembic.ini, this will be used.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = context.get_x_argument(as_dictionary=True).get('connection')

    if connectable is None:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        # Enable batch mode for SQLite
        is_sqlite = connection.dialect.name == 'sqlite'
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
