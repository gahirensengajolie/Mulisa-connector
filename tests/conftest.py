"""Shared fixtures.

A real mock Mulisa on a random local port and the real app on a temp SQLite file."""

import itertools
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.migrations import upgrade_to_head
from app.main import create_app
from mock_mulisa.server import make_server

CONNECTOR_KEY = "test-connector-key-0123456789"
MULISA_KEY = "test-mulisa-key-0123456789"

_counter = itertools.count(1)


def make_payment(**overrides: Any) -> dict[str, Any]:
    """A valid payment with a fresh reference. Pass reference=... to reuse one."""
    payment: dict[str, Any] = {
        "reference": f"GB-T-{next(_counter):06d}",
        "amount": "250000",
        "currency": "RWF",
        "debtor": {
            "msisdn": "250788000111",
            "name": "Aline Uwase",
            "wallet": "GB-0001",
        },
        "creditor": {
            "msisdn": "250722000333",
            "name": "Eric Mugisha",
            "provider": "bluemobile",
        },
        "createdAt": "2026-10-14T16:40:00Z",
    }
    payment.update(overrides)
    return payment


@pytest.fixture
def payment() -> Callable[..., dict[str, Any]]:
    return make_payment


@dataclass
class MockMulisa:
    server: Any

    @property
    def state(self) -> Any:
        return self.server.state

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def set_mode(self, mode: str, delay: float | None = None) -> None:
        self.state.mode = mode
        if delay is not None:
            self.state.delay = delay

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def mulisa() -> Iterator[MockMulisa]:
    server = make_server(port=0, api_key=MULISA_KEY)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    mock = MockMulisa(server)
    mock.state.delay = 0.8
    yield mock
    if thread.is_alive():
        mock.stop()


@pytest.fixture
def make_settings(tmp_path: Path, mulisa: MockMulisa) -> Callable[..., Settings]:
    def _make(*, migrate: bool = True, **overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "screening_unavailable_policy": "fail_closed",
            "connector_api_keys": f"core-banking={CONNECTOR_KEY}",
            "mulisa_url": mulisa.url,
            "mulisa_api_key": MULISA_KEY,
            "mulisa_timeout_seconds": 0.3,
            "mulisa_retry_delay_seconds": 0.02,
            "database_url": f"sqlite:///{tmp_path / 'test.db'}",
        }
        values.update(overrides)
        settings = Settings(_env_file=None, **values)
        if migrate:
            upgrade_to_head(settings.database_url)  # same path as production: alembic
        return settings

    return _make


@pytest.fixture
def client(make_settings: Callable[..., Settings]) -> TestClient:
    # Not used as a context manager on purpose: all state is created in create_app().
    return TestClient(create_app(make_settings()), headers={"X-Api-Key": CONNECTOR_KEY})
