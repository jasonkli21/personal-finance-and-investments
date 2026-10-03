"""HTTP entry point and lifecycle for the finance modular monolith."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response

from app.api.finance_routes import router as finance_router
from app.api.fund_routes import router as fund_router
from app.api.job_routes import router as job_router
from app.api.report_routes import router as report_router
from app.api.research_routes import router as research_router
from app.api.routes import router as api_router
from app.api.stage3_history_routes import router as stage3_history_router
from app.api.stage3_planning_routes import router as stage3_planning_router
from app.api.stage3_portfolio_scenario_routes import (
    router as stage3_portfolio_scenario_router,
)
from app.api.stage3_sales_routes import router as stage3_sales_router
from app.api.stage3_tax_routes import router as stage3_tax_router
from app.api.transaction_routes import router as transaction_router
from app.auth.oidc import OIDC_TRANSACTION_COOKIE, create_oidc_client
from app.auth.routes import router as auth_router
from app.auth.service import SESSION_COOKIE, PrincipalContext, get_principal
from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.integrations.personal_ai import DisabledPersonalAIClient
from app.storage.factory import create_file_store

# The container's Uvicorn logger already has an INFO handler. Use it for the
# redacted request records that replace Uvicorn's query-bearing access log.
logger = logging.getLogger("uvicorn.error")


def _database_unavailable(request: Request, error: SQLAlchemyError) -> JSONResponse:
    # Driver text, SQL and bound parameters can contain personal data or tokens.
    # Keep a request-correlated failure signal without logging the exception.
    logger.error(
        "Database request failed request_id=%s error_type=%s",
        request.state.correlation_id,
        type(error).__name__,
    )
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


class HealthResponse(BaseModel):
    status: str


def create_app(*, engine: Engine | None = None) -> FastAPI:
    settings = load_settings()
    database_engine = engine or DatabaseEngineFactory.create(settings)
    session_factory: sessionmaker[Session] = sessionmaker(
        bind=database_engine, expire_on_commit=False
    )
    file_store = create_file_store(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker_task: asyncio.Task[None] | None = None
        try:
            if settings.job_worker_enabled:
                from app.jobs.runner import run_worker

                worker_task = asyncio.create_task(
                    run_worker(
                        session_factory,
                        file_store,
                        poll_interval_seconds=settings.job_poll_interval_seconds,
                        lease_seconds=settings.job_lease_seconds,
                    )
                )
            yield
        finally:
            try:
                if worker_task is not None:
                    worker_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker_task
            finally:
                # A failed worker must not skip connection-pool cleanup.
                database_engine.dispose()

    app = FastAPI(
        title="Portfolio Intelligence API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None if settings.app_env == "production" else "/redoc",
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )
    app.state.database_engine = database_engine
    app.state.session_factory = session_factory
    app.state.settings = settings
    app.state.private_file_root = settings.private_file_dir
    app.state.file_store = file_store
    app.state.oidc_client = create_oidc_client(settings)
    app.state.max_import_file_bytes = settings.max_import_file_bytes
    app.state.max_private_file_bytes = settings.max_private_file_bytes
    app.state.max_import_rows = settings.max_import_rows
    app.state.max_pdf_pages = settings.max_pdf_pages
    app.state.pdf_parser_timeout_seconds = settings.pdf_parser_timeout_seconds
    app.state.job_worker_enabled = settings.job_worker_enabled
    app.state.job_poll_interval_seconds = settings.job_poll_interval_seconds
    app.state.job_lease_seconds = settings.job_lease_seconds
    app.state.job_max_attempts = settings.job_max_attempts
    app.state.personal_ai_client = DisabledPersonalAIClient()
    for router in (
        auth_router,
        api_router,
        research_router,
        transaction_router,
        finance_router,
        job_router,
        fund_router,
        report_router,
        stage3_history_router,
        stage3_portfolio_scenario_router,
        stage3_planning_router,
        stage3_sales_router,
        stage3_tax_router,
    ):
        app.include_router(router)

    if settings.auth_enabled:
        signing_key = settings.auth_session_signing_key
        if signing_key is None:
            raise ValueError("OIDC transaction signing key is required")
        app.add_middleware(
            SessionMiddleware,
            secret_key=signing_key,
            session_cookie=OIDC_TRANSACTION_COOKIE,
            max_age=600,
            path="/",
            same_site="lax",
            https_only=settings.auth_cookie_secure,
        )

    @app.middleware("http")
    async def authorize_financial_routes(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request.state.correlation_id = str(uuid4())
        started_at = time.monotonic()
        path = request.url.path
        response: Response | None = None
        if settings.auth_enabled and path.startswith("/v1"):
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin != settings.app_public_origin:
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Request origin is not allowed"},
                    )
                elif request.headers.get("sec-fetch-site") == "cross-site":
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-site requests are not allowed"},
                    )
            if response is None and path not in {
                "/v1/auth/login",
                "/v1/auth/callback",
            }:
                try:
                    principal: PrincipalContext | None = await run_in_threadpool(
                        get_principal,
                        session_factory,
                        settings,
                        request.cookies.get(SESSION_COOKIE),
                    )
                except SQLAlchemyError as exc:
                    response = _database_unavailable(request, exc)
                    principal = None
                if principal is None and response is None:
                    response = JSONResponse(
                        status_code=401,
                        content={"detail": "Authentication required"},
                    )
                request.state.principal = principal
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path.startswith("/v1"):
            response.headers["Cache-Control"] = "no-store"
            # Log route templates, never query strings or user-provided paths.
            # OIDC callbacks contain credentials in their query parameters.
            route = request.scope.get("route")
            logger.info(
                "HTTP request completed request_id=%s method=%s route=%s "
                "status=%s duration_ms=%.1f",
                request.state.correlation_id,
                request.method,
                getattr(route, "path", "<unmatched>"),
                response.status_code,
                (time.monotonic() - started_at) * 1000,
            )
        return response

    @app.exception_handler(SQLAlchemyError)
    def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        return _database_unavailable(request, exc)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        try:
            with database_engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return HealthResponse(status="ready")

    return app


app = create_app()
