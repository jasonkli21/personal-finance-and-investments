"""Construct standard PostgreSQL engines for local PostgreSQL and Neon."""

from typing import Literal

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

from app.config import Settings
from app.db.urls import postgres_url

EnginePurpose = Literal["application", "migration"]


class DatabaseEngineFactory:
    @staticmethod
    def create(settings: Settings, *, purpose: EnginePurpose = "application") -> Engine:
        explicit = (
            (settings.migration_database_url or settings.database_url)
            if purpose == "migration"
            else settings.database_url
        )
        url = (
            postgres_url(explicit, production=settings.app_env == "production")
            if explicit
            else URL.create(
                "postgresql+psycopg",
                username=settings.database_user,
                password=settings.database_password,
                host=settings.database_host,
                port=settings.database_port,
                database=settings.database_name,
            )
        )
        return create_engine(
            url,
            connect_args={"connect_timeout": settings.database_connect_timeout_seconds},
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_pre_ping=True,
            pool_recycle=settings.database_pool_recycle_seconds,
            pool_timeout=settings.database_connect_timeout_seconds,
        )
