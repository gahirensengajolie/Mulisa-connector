"""Alembic environment: connects migrations to our models and to DATABASE_URL.

Run from the project root:
    alembic upgrade head                              apply every migration
    alembic revision --autogenerate -m "add column"   draft a migration from model changes
    alembic downgrade -1                              undo the last migration
"""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_database_url
from app.db.session import Base, make_engine
from app.models import screening as _models  # noqa: F401  (registers the table on Base)

config = context.config
# Logging is configured only when run from the command line; tests and the application run
# migrations in-process and set this to False so they keep their own logging.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    # A URL set on the Alembic config (tests, programmatic use) wins over the environment.
    return config.get_main_option("sqlalchemy.url") or get_database_url()


def run_migrations_offline() -> None:
    """Write the SQL instead of running it:  alembic upgrade head --sql"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_engine(_database_url())  # same engine rules as the application
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                # SQLite cannot ALTER most things in place: "batch" mode rebuilds the table.
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
