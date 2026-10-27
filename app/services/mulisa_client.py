"""Client for Mulisa's POST /api/screen (standard library only).

Rules:
  * a timeout on EVERY call;
  * at most ONE retry, and only when the call timed out or Mulisa's error says "retryable": true;
  * the retry re-sends the identical bytes, so transaction.id is unchanged and Mulisa's own
    idempotency makes the retry safe.
The client never raises for upstream trouble: it returns a typed outcome and the service
applies the bank's policy.
"""

import http.client
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.core.log import log_event
from app.schemas.mulisa import MulisaScreenRequest, MulisaScreenResponse

_MAX_RESPONSE_BYTES = 1024 * 1024

TIMEOUT = "timeout"
UPSTREAM_ERROR = "upstream_error"  
UPSTREAM_REJECTED = "upstream_rejected"  
UPSTREAM_UNREACHABLE = "upstream_unreachable"  
UPSTREAM_BAD_RESPONSE = "upstream_bad_response"

@dataclass(frozen=True)
class Decided:
    result: MulisaScreenResponse
    attempts: int


@dataclass(frozen=True)
class Unavailable:
    reason: str
    attempts: int


@dataclass(frozen=True)
class _Attempt:
    result: MulisaScreenResponse | None = None
    reason: str | None = None
    retryable: bool = False
    http_status: int | None = None


def _read_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:  
        return None


class MulisaClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float,
        retry_delay: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = base_url.rstrip("/") + "/api/screen"
        self._api_key = api_key
        self._timeout = timeout
        self._retry_delay = retry_delay
        self._sleep = sleep

    def screen(self, request: MulisaScreenRequest, request_id: str) -> Decided | Unavailable:
        payload = request.model_dump_json(exclude_none=True).encode()  
        last = _Attempt()
        for attempt_no in (1, 2):  
            last = self._call_once(payload, request_id)
            log_event(
                "mulisa_attempt",
                level=logging.INFO if last.result else logging.WARNING,
                request_id=request_id,
                attempt=attempt_no,
                outcome="ok" if last.result else last.reason,
                http_status=last.http_status,
            )
            if last.result is not None:
                return Decided(result=last.result, attempts=attempt_no)
            if attempt_no == 1 and last.retryable:
                self._sleep(self._retry_delay)
                continue
            return Unavailable(reason=last.reason or UPSTREAM_ERROR, attempts=attempt_no)
        return Unavailable(reason=last.reason or UPSTREAM_ERROR, attempts=2)  

    def _call_once(self, payload: bytes, request_id: str) -> _Attempt:
        http_request = urllib.request.Request(  
            self._url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-Api-Key": self._api_key,
                "X-Request-Id": request_id,
            },
        )
        try:
            with _opener.open(http_request, timeout=self._timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES)
                status = response.status
        except urllib.error.HTTPError as exc:  
            return self._from_error_status(exc.code, exc.read(_MAX_RESPONSE_BYTES))
        except TimeoutError:
            return _Attempt(reason=TIMEOUT, retryable=True)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return _Attempt(reason=TIMEOUT, retryable=True)
            return _Attempt(reason=UPSTREAM_UNREACHABLE)
        except (OSError, http.client.HTTPException):
            return _Attempt(reason=UPSTREAM_UNREACHABLE)

        try:
            result = MulisaScreenResponse.model_validate(_read_json(raw))
        except ValidationError:
            return _Attempt(reason=UPSTREAM_BAD_RESPONSE, http_status=status)
        return _Attempt(result=result, http_status=status)

    @staticmethod
    def _from_error_status(status: int, raw: bytes) -> _Attempt:
        body = _read_json(raw)
        envelope = body.get("error") if isinstance(body, dict) else None
        if not isinstance(envelope, dict):
            envelope = body if isinstance(body, dict) else {}
        retryable = envelope.get("retryable") is True
        reason = UPSTREAM_REJECTED if 400 <= status < 500 else UPSTREAM_ERROR
        return _Attempt(reason=reason, retryable=retryable, http_status=status)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: it could forward our API key to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  
        return None


_opener = urllib.request.build_opener(_NoRedirect)
