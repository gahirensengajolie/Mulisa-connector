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
    screening_unavailable_policy: Literal["fail_open", "fail_closed"]
    connector_api_keys: SecretStr
    mulisa_url: str
    mulisa_api_key: SecretStr

    mulisa_timeout_seconds: float = Field(default=3.0, ge=0.05, le=30)
    mulisa_retry_delay_seconds: float = Field(default=0.2, ge=0, le=5)
    bank_institution_id: str = Field(default="greenbank", min_length=1, max_length=32)
    bank_country: str = Field(default="RW", pattern=r"^[A-Z]{2}$")
    database_url: str = "sqlite:///data/connector.db"

    @field_validator("connector_api_keys")
    @classmethod
    def _check_api_keys(cls, value: SecretStr) -> SecretStr:
        parse_api_keys(value.get_secret_value())  
        return value

    @field_validator("mulisa_api_key")
    @classmethod
    def _check_mulisa_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret or secret.startswith("CHANGE_ME"):
            raise ValueError("MULISA_API_KEY is empty or still the .env.example placeholder")
        return value

    @field_validator("mulisa_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme == "https" and parsed.hostname:
            return value.rstrip("/")
        if parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS:
            return value.rstrip("/")
        raise ValueError("MULISA_URL must be https (plain http is only allowed for localhost)")

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
            raise ValueError(f"API key for '{name}' is too short (minimum 16 characters)")
        if key.startswith("CHANGE_ME"):
            raise ValueError(f"API key for '{name}' is still the .env.example placeholder")
        if key in keys.values():
            raise ValueError("API keys must be unique per calling system")
        keys[name] = key
    return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()