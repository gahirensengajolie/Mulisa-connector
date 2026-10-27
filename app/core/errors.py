"""One error shape for every failure: {"error": {"code", "message", "request_id", "details"?}}.
Never a stack trace, never an echoed value."""

from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.log import log_event


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class ReferenceConflict(ApiError):
    def __init__(self) -> None:
        super().__init__(
            409,
            "reference_conflict",
            "this reference was already used for a different payment",
        )


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[dict[str, Any]] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    return JSONResponse(
        status_code=status_code,
        content={"error": body},
        headers={"X-Request-Id": request_id},
    )


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    error = cast(ApiError, exc)
    return error_response(
        request, error.status_code, error.code, error.message, error.details
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    errors = cast(RequestValidationError, exc).errors()
    if any(err.get("type") == "json_invalid" for err in errors):
        return error_response(request, 400, "invalid_json", "body is not valid JSON")
    # Field and rule only. err["input"] (the offending value) is deliberately dropped.
    details = [
        {
            "field": ".".join(str(part) for part in err["loc"][1:]) or "$",
            "code": err["type"],
            "message": err["msg"],
        }
        for err in errors
    ]
    return error_response(
        request, 422, "validation_failed", "the payment message is invalid", details
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    status = cast(StarletteHTTPException, exc).status_code
    codes = {404: "not_found", 405: "method_not_allowed"}
    return error_response(
        request, status, codes.get(status, "http_error"), "request refused"
    )


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Log the error TYPE only: the message could contain customer data.
    log_event(
        "internal_error",
        request_id=getattr(request.state, "request_id", None),
        error_type=type(exc).__name__,
    )
    return error_response(request, 500, "internal_error", "something went wrong")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
