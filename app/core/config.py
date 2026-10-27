"""Settings come from environment variables (or a git-ignored .env file).
Anything required and missing stops the application at startup."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The bank's decision, not the code's: NO default, so the app refuses to start without it.
    screening_unavailable_policy: Literal["fail_open", "fail_closed"]

    # "name=key,name2=key2": one key per calling system (so one can be revoked alone).
    connector_api_keys: SecretStr
    mulisa_url: str
    mulisa_api_key: SecretStr

    mulisa_timeout_seconds: float = Field(default=3.0, ge=0.05, le=30)
    mulisa_retry_delay_seconds: float = Field(default=0.2, ge=0, le=5)
    bank_institution_id: str = Field(default="greenbank", min_length=1, max_length=32)
    bank_country: str = Field(default="RW", pattern=r"^[A-Z]{2}$")
    database_url: str = "sqlite:///data/connector.db"

    # Mulisa's transaction.id is unique across ALL banks: ours is "<prefix>-<reference>".
    transaction_id_prefix: str = Field(
        default="", max_length=32, pattern=r"^[A-Za-z0-9_-]*$"
    )
    mulisa_transaction_type: str = Field(
        default="transfer", min_length=1, max_length=32
    )
    mulisa_channel: str = Field(default="api", min_length=1, max_length=32)
    # A payment dated further than this into the future is rejected (clock drift allowance).
    max_future_skew_seconds: int = Field(default=300, ge=0, le=86400)
    # /docs and /openapi.json describe the API to strangers: off unless explicitly enabled.
    enable_api_docs: bool = False

    @field_validator("connector_api_keys")
    @classmethod
    def _check_api_keys(cls, value: SecretStr) -> SecretStr:
        parse_api_keys(
            value.get_secret_value()
        )  # raises ValueError with a clear message
        return value

    @field_validator("mulisa_api_key")
    @classmethod
    def _check_mulisa_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret or secret.startswith("CHANGE_ME"):
            raise ValueError(
                "MULISA_API_KEY is empty or still the .env.example placeholder"
            )
        return value

    @field_validator("mulisa_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.hostname:
            return value.rstrip("/")
        if parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS:
            return value.rstrip("/")
        # The API key and customer data travel in this request: no cleartext outside localhost.
        raise ValueError(
            "MULISA_URL must be https (plain http is only allowed for localhost)"
        )

    @property
    def id_prefix(self) -> str:
        return self.transaction_id_prefix or self.bank_institution_id

    @property
    def api_keys(self) -> dict[str, str]:
        return parse_api_keys(self.connector_api_keys.get_secret_value())


def parse_api_keys(raw: str) -> dict[str, str]:
    keys: dict[str, str] = {}
    for pair in raw.split(","):
        name, sep, key = pair.partition("=")
        name, key = name.strip(), key.strip()
        if not sep or not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("CONNECTOR_API_KEYS entries must look like name=key")
        if len(key) < 16:
            raise ValueError(
                f"API key for '{name}' is too short (minimum 16 characters)"
            )
        if key.startswith("CHANGE_ME"):
            raise ValueError(
                f"API key for '{name}' is still the .env.example placeholder"
            )
        if key in keys.values():
            raise ValueError("API keys must be unique per calling system")
        keys[name] = key
    return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # values come from the environment
