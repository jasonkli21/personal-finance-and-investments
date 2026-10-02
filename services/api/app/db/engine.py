"""Construct database engines behind one explicit backend boundary."""

from collections.abc import Callable
from typing import Literal

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL

from app.config import Settings

EnginePurpose = Literal["application", "migration"]
DsqlEngineBuilder = Callable[..., Engine]


class DatabaseEngineFactory:
    """Build PostgreSQL or IAM-authenticated Aurora DSQL engines."""

    @staticmethod
    def create(
        settings: Settings,
        *,
        purpose: EnginePurpose = "application",
        dsql_engine_builder: DsqlEngineBuilder | None = None,
    ) -> Engine:
        common_pool_options = {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_pre_ping": True,
            "pool_recycle": settings.database_pool_recycle_seconds,
            "pool_timeout": settings.database_connect_timeout_seconds,
        }
        if settings.database_backend == "postgres":
            connect_args = {
                "connect_timeout": settings.database_connect_timeout_seconds
            }
            if settings.database_url is not None:
                return create_engine(
                    settings.database_url,
                    connect_args=connect_args,
                    **common_pool_options,
                )
            url = URL.create(
                "postgresql+psycopg",
                username=settings.database_user,
                password=settings.database_password,
                host=settings.database_host,
                port=settings.database_port,
                database=settings.database_name,
            )
            return create_engine(url, connect_args=connect_args, **common_pool_options)

        if settings.database_backend != "aurora_dsql":
            raise ValueError(
                f"Unsupported database backend: {settings.database_backend}"
            )
        if purpose == "application":
            user = settings.aurora_dsql_db_user
        else:
            user = settings.aurora_dsql_migration_db_user
            if user is None:
                raise ValueError(
                    "AURORA_DSQL_MIGRATION_DB_USER is required for DSQL migrations"
                )
        if (
            user is None
            or settings.aws_region is None
            or settings.aurora_dsql_cluster_endpoint is None
        ):
            raise ValueError("Aurora DSQL engine settings are incomplete")
        builder = dsql_engine_builder
        if builder is None:
            from aurora_dsql_sqlalchemy import (  # type: ignore[import-untyped]
                create_dsql_engine,
            )

            builder = create_dsql_engine
        return builder(
            host=settings.aurora_dsql_cluster_endpoint,
            user=user,
            driver="psycopg",
            dbname="postgres",
            sslmode="verify-full",
            sslrootcert="system",
            connect_args={
                "region": settings.aws_region,
                "connect_timeout": settings.database_connect_timeout_seconds,
            },
            **common_pool_options,
        )
