from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE: dict[str, Any] = {
    "screening_unavailable_policy": "fail_closed",
    "connector_api_keys": "core=abcdefghijklmnopqrstuv",
    "mulisa_url": "http://127.0.0.1:9100",
    "mulisa_api_key": "a-real-looking-mulisa-key",
}


def make(**over: Any) -> Settings:
    return Settings(_env_file=None, **{**BASE, **over})


def test_the_policy_is_required_and_has_no_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCREENING_UNAVAILABLE_POLICY", raising=False)
    assert make().screening_unavailable_policy == "fail_closed"
    values = {k: v for k, v in BASE.items() if k != "screening_unavailable_policy"}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize("bad", ["", "maybe", "FAIL_OPEN"])
def test_an_unknown_policy_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        make(screening_unavailable_policy=bad)


@pytest.mark.parametrize(
    "over",
    [
        {"connector_api_keys": "core=CHANGE_ME_generate_a_long_random_key"},
        {"connector_api_keys": "core=short"},
        {"connector_api_keys": "a=abcdefghijklmnopqrstuv,b=abcdefghijklmnopqrstuv"},
        {"mulisa_api_key": "CHANGE_ME_mulisa_key"},
        {"mulisa_url": "http://mulisa.example.com"},  # cleartext to a remote host
        {"mulisa_timeout_seconds": 0},
    ],
)
def test_placeholders_short_keys_and_cleartext_remote_urls_are_refused(
    over: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        make(**over)


def test_https_is_accepted_and_keys_are_parsed_per_caller() -> None:
    settings = make(
        mulisa_url="https://mulisa.example.com/",
        connector_api_keys="a=abcdefghijklmnop,b=qrstuvwxyz012345",
    )
    assert settings.mulisa_url == "https://mulisa.example.com"
    assert list(settings.api_keys) == ["a", "b"]
