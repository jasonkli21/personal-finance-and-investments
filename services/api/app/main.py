"""HTTP entry point for the Stage 0 API."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory


class HealthResponse(BaseModel):
    status: str


def create_app(*, engine: Engine | None = None) -> FastAPI:
    settings = load_settings()
    database_engine = engine or DatabaseEngineFactory.create(settings)

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
