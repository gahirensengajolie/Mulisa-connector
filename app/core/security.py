"""API-key authentication. Deny by default: no valid key, no access."""

import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, Request

from app.core.config import Settings
from app.core.errors import ApiError


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def require_api_key(
    request: Request, settings: Annotated[Settings, Depends(get_settings_dep)]
) -> str:
    """Returns the calling system's name. Compares hashes in constant time against EVERY key
    (no early exit), so timing reveals nothing about which key was close."""
    provided = request.headers.get("x-api-key", "")
    if not provided:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
    if not provided or len(provided) > 256:
        raise ApiError(401, "unauthenticated", "missing or invalid API key")

    digest = hashlib.sha256(provided.encode()).digest()
    caller: str | None = None
    for name, key in settings.api_keys.items():
        if hmac.compare_digest(digest, hashlib.sha256(key.encode()).digest()):
            caller = name
    if caller is None:
        raise ApiError(401, "unauthenticated", "missing or invalid API key")
    return caller
