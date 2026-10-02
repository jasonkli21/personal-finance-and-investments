"""HTTP entry point for the Stage 1 finance API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes import router as api_router
from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.integrations.personal_ai import DisabledPersonalAIClient


class HealthResponse(BaseModel):
    status: str


def create_app(*, engine: Engine | None = None) -> FastAPI:
    settings = load_settings()
    database_engine = engine or DatabaseEngineFactory.create(settings)
    session_factory: sessionmaker[Session] = sessionmaker(
        bind=database_engine, expire_on_commit=False
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            database_engine.dispose()

    app = FastAPI(
        title="Portfolio Intelligence API", version="0.1.0", lifespan=lifespan
    )
    app.state.database_engine = database_engine
    app.state.session_factory = session_factory
    app.state.private_file_root = settings.private_file_dir
    app.state.max_import_file_bytes = settings.max_import_file_bytes
    app.state.max_import_rows = settings.max_import_rows
    app.state.personal_ai_client = DisabledPersonalAIClient()
    app.include_router(api_router)
    from app.api.fund_routes import router as fund_router

    app.include_router(fund_router)
    from app.api.report_routes import router as report_router

    app.include_router(report_router)

    @app.exception_handler(SQLAlchemyError)
    def database_error_handler(
        _request: Request, _exc: SQLAlchemyError
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

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
