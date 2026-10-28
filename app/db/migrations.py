"""Programmatic access to Alembic: used by the startup check and by the tests."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SchemaNotCurrent(Exception):
    """The database has not been migrated to the version this code expects."""


def alembic_config(url: str | None = None) -> Config:
    """Alembic config that works from any working directory."""
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    if url is not None:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # configparser escape
    config.attributes["configure_logger"] = False
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def upgrade_to_head(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def assert_schema_current(engine: Engine) -> None:
    """Refuse to run against a database that is behind (or ahead of) the code."""
    current, expected = current_revision(engine), head_revision()
    if current != expected:
        raise SchemaNotCurrent(
            f"Database schema is not up to date (database: {current or 'not migrated'}, "
            f"expected: {expected}). Run:  alembic upgrade head"
        )
