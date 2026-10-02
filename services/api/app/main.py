"""HTTP entry point for the Stage 0 API."""

import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.config import load_settings


class HealthResponse(BaseModel):
    status: str


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="Portfolio Intelligence API", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/health/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        try:
            if settings.database_url is not None:
                connection = psycopg.connect(
                    conninfo=settings.database_url, connect_timeout=2
                )
            else:
                connection = psycopg.connect(
                    host=settings.database_host,
                    port=settings.database_port,
                    user=settings.database_user,
                    password=settings.database_password,
                    dbname=settings.database_name,
                    connect_timeout=2,
                )
            with connection:
                connection.execute("SELECT 1")
        except psycopg.Error as exc:
            raise HTTPException(status_code=503, detail="Database unavailable") from exc
        return HealthResponse(status="ready")

    return app


app = create_app()
