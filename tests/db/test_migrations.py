"""The Alembic migrations.

They build the schema, match the models, undo cleanly, and gate startup."""

import io
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text

from app.core.config import DEFAULT_DATABASE_URL, Settings, get_database_url
from app.db.migrations import (
    SchemaNotCurrent,
    alembic_config,
    assert_schema_current,
    current_revision,
    head_revision,
    upgrade_to_head,
)
from app.db.session import Base, make_engine, make_session_factory
from app.main import create_app
from app.models import screening as _models  # noqa: F401  (registers the table on Base)
from app.models.screening import ScreeningRecord
from app.repositories.screening_repository import (
    RecordAlreadyExists,
    ScreeningRepository,
)

FIRST_REVISION = "0001"


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'migrations.db'}"


@pytest.fixture
def engine(db_url: str) -> Engine:
    return create_engine(db_url)


def record(reference: str) -> ScreeningRecord:
    return ScreeningRecord(
        reference=reference,
        payload_hash="h" * 64,
        decision="cleared",
        recommended_action="release",
        attempts=1,
    )


class TestUpgrade:
    def test_creates_the_table_with_every_column(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        columns = {c["name"]: c for c in inspect(engine).get_columns("screening_records")}
        assert set(columns) == {
            "id",
            "reference",
            "payload_hash",
            "decision",
            "recommended_action",
            "screening_id",
            "risk_score",
            "matched_rules",
            "attempts",
            "created_at",
        }
        assert columns["reference"]["nullable"] is False
        assert columns["screening_id"]["nullable"] is True
        assert columns["risk_score"]["nullable"] is True

    def test_reference_has_a_unique_index(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        indexes = {i["name"]: i for i in inspect(engine).get_indexes("screening_records")}
        assert indexes["ix_screening_records_reference"]["unique"]
        assert indexes["ix_screening_records_reference"]["column_names"] == ["reference"]

    def test_records_the_revision_in_the_database(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        assert current_revision(engine) == head_revision() == FIRST_REVISION

    def test_running_it_twice_changes_nothing(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        upgrade_to_head(db_url)
        assert current_revision(engine) == FIRST_REVISION
        assert inspect(engine).get_table_names().count("screening_records") == 1

    def test_the_database_refuses_a_duplicate_reference(self, db_url: str) -> None:
        upgrade_to_head(db_url)
        session = make_session_factory(make_engine(db_url))()
        repository = ScreeningRepository(session)
        repository.add(record("GB-1"))
        with pytest.raises(RecordAlreadyExists):
            repository.add(record("GB-1"))

    def test_creates_the_data_folder_for_a_sqlite_file(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'not' / 'yet' / 'there.db'}"
        upgrade_to_head(url)
        assert (tmp_path / "not" / "yet" / "there.db").exists()


class TestMigrationsMatchTheModels:
    def test_no_difference_between_the_migrated_database_and_the_models(
        self, db_url: str, engine: Engine
    ) -> None:
        """If you change a model and forget the migration, this fails."""
        upgrade_to_head(db_url)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []

    def test_there_is_exactly_one_head(self) -> None:
        assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


class TestDowngrade:
    def test_removes_the_table_and_the_revision(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        command.downgrade(alembic_config(db_url), "base")
        assert "screening_records" not in inspect(engine).get_table_names()
        assert current_revision(engine) is None

    def test_can_upgrade_again_afterwards(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        command.downgrade(alembic_config(db_url), "base")
        upgrade_to_head(db_url)
        assert current_revision(engine) == FIRST_REVISION


class TestHowTheUrlIsChosen:
    def test_env_py_needs_only_database_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        db_url: str,
        engine: Engine,
    ) -> None:
        """Migrations must not require the policy, the API keys or the Mulisa settings."""
        for name in (
            "SCREENING_UNAVAILABLE_POLICY",
            "CONNECTOR_API_KEYS",
            "MULISA_URL",
            "MULISA_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("DATABASE_URL", db_url)
        command.upgrade(
            alembic_config(), "head"
        )  # no URL passed in: it must come from the environment
        assert current_revision(engine) == FIRST_REVISION

    def test_the_default_matches_the_application_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)  # no .env file here
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert (
            get_database_url()
            == DEFAULT_DATABASE_URL
            == Settings.model_fields["database_url"].default
        )

    def test_a_percent_sign_in_the_url_survives(self) -> None:
        url = "postgresql://user:p%40ss@localhost/db"
        assert alembic_config(url).get_main_option("sqlalchemy.url") == url

    def test_offline_mode_writes_sql_without_touching_a_database(
        self, db_url: str, tmp_path: Path
    ) -> None:
        config = alembic_config(db_url)
        config.output_buffer = io.StringIO()
        command.upgrade(config, "head", sql=True)
        sql = config.output_buffer.getvalue()
        assert "CREATE TABLE screening_records" in sql
        assert "CREATE UNIQUE INDEX ix_screening_records_reference" in sql
        assert not (tmp_path / "migrations.db").exists()


class TestStartupGate:
    def test_an_unmigrated_database_stops_the_application_with_instructions(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        with pytest.raises(SystemExit) as caught:
            create_app(make_settings(migrate=False))
        message = str(caught.value)
        assert "alembic upgrade head" in message
        assert "not migrated" in message

    def test_after_migrating_the_application_starts(
        self, make_settings: Callable[..., Settings]
    ) -> None:
        settings = make_settings(migrate=False)
        upgrade_to_head(settings.database_url)
        assert TestClient(create_app(settings)).get("/health").status_code == 200

    def test_a_database_at_an_unknown_revision_is_refused_and_both_revisions_are_named(
        self, db_url: str, engine: Engine
    ) -> None:
        upgrade_to_head(db_url)
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = 'zzzz'"))
        with pytest.raises(SchemaNotCurrent) as caught:
            assert_schema_current(engine)
        assert "zzzz" in str(caught.value)
        assert FIRST_REVISION in str(caught.value)

    def test_a_current_database_passes_the_check(self, db_url: str, engine: Engine) -> None:
        upgrade_to_head(db_url)
        assert_schema_current(engine)  # does not raise
