"""Application factory. Run with:  uvicorn app.main:create_app --factory"""

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import error_response, register_error_handlers
from app.core.log import configure_logging, log_event
from app.db.session import Base, make_engine, make_session_factory
from app.models import screening as _models  # noqa: F401  (registers the table on Base)
from app.routers import health, screening
from app.services.mulisa_client import MulisaClient
from app.services.screening_service import ReferenceLocks

MAX_BODY_BYTES = 16 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        try:
            settings = get_settings()
        except ValidationError as exc:
            # Name the settings that are wrong, never their values (they may be keys).
            wrong = ", ".join(
                sorted({str(err["loc"][0]).upper() for err in exc.errors() if err["loc"]})
            )
            raise SystemExit(
                f"Configuration error: check {wrong} (see .env.example and the README)"
            ) from None
    configure_logging()

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)  # a real deployment would use migrations (Alembic)

    docs = settings.enable_api_docs
    app = FastAPI(
        title="Mulisa screening connector",
        version="1.0.0",
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.reference_locks = ReferenceLocks()
    app.state.mulisa_client = MulisaClient(
        settings.mulisa_url,
        settings.mulisa_api_key.get_secret_value(),
        settings.mulisa_timeout_seconds,
        settings.mulisa_retry_delay_seconds,
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return error_response(
                request,
                413,
                "payload_too_large",
                f"body must be at most {MAX_BODY_BYTES} bytes",
            )
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        response.headers["Cache-Control"] = "no-store"
        log_event(
            "http_request", request_id=request_id, method=request.method, path=request.url.path,
            status=response.status_code, ms=round((time.perf_counter() - started) * 1000),
        )  # fmt: skip
        return response

    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(screening.router)
    return app
