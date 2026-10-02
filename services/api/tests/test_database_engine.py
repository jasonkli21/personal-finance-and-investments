"""Verify backend routing and DSQL security defaults without AWS access."""

import pytest
from aurora_dsql_sqlalchemy import create_dsql_engine  # type: ignore[import-untyped]
from sqlalchemy import Engine, create_engine
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.db.models import Base


def test_dsql_engine_uses_official_builder_and_verified_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AURORA_DSQL_CLUSTER_ENDPOINT", "test.dsql.us-west-2.on.aws")
    monkeypatch.setenv("AURORA_DSQL_DB_USER", "portfolio_app")
    monkeypatch.setenv("AURORA_DSQL_MIGRATION_DB_USER", "portfolio_migrator")
    settings = load_settings()
    calls: list[dict[str, object]] = []

    def builder(**kwargs: object) -> Engine:
        calls.append(kwargs)
        return create_engine("sqlite://")

    engine = DatabaseEngineFactory.create(settings, dsql_engine_builder=builder)
    engine.dispose()

    assert calls == [
        {
            "host": "test.dsql.us-west-2.on.aws",
            "user": "portfolio_app",
            "driver": "psycopg",
            "dbname": "postgres",
            "sslmode": "verify-full",
            "sslrootcert": "system",
            "connect_args": {"region": "us-west-2", "connect_timeout": 3},
            "pool_size": 5,
            "max_overflow": 5,
            "pool_pre_ping": True,
            "pool_recycle": 3000,
            "pool_timeout": 3,
        }
    ]


def test_dsql_migrations_use_a_separate_database_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AURORA_DSQL_CLUSTER_ENDPOINT", "test.dsql.us-east-1.on.aws")
    monkeypatch.setenv("AURORA_DSQL_DB_USER", "portfolio_app")
    monkeypatch.setenv("AURORA_DSQL_MIGRATION_DB_USER", "portfolio_migrator")
    settings = load_settings()
    calls: list[dict[str, object]] = []

    def builder(**kwargs: object) -> Engine:
        calls.append(kwargs)
        return create_engine("sqlite://")

    engine = DatabaseEngineFactory.create(
        settings, purpose="migration", dsql_engine_builder=builder
    )
    engine.dispose()
    assert calls[0]["user"] == "portfolio_migrator"


def test_official_dsql_dialect_compiles_core_schema_without_connecting() -> None:
    engine = create_dsql_engine(
        host="compile-only.dsql.us-east-1.on.aws",
        user="portfolio_app",
        connect_args={"region": "us-east-1"},
    )
    try:
        assert engine.dialect.name == "auroradsql"
        table_ddl = [
            str(CreateTable(table).compile(dialect=engine.dialect))
            for table in Base.metadata.sorted_tables
        ]
        index_ddl = [
            str(CreateIndex(index).compile(dialect=engine.dialect))
            for table in Base.metadata.sorted_tables
            for index in table.indexes
        ]
        assert len(table_ddl) == 17
        assert len(index_ddl) == 11
        assert all(
            statement.lstrip().startswith("CREATE TABLE") for statement in table_ddl
        )
        assert all(
            statement.startswith("CREATE INDEX ASYNC") for statement in index_ddl
        )
        assert any("JSONB" in statement for statement in table_ddl)
        assert any("NUMERIC(28, 10)" in statement for statement in table_ddl)
        assert any("ON DELETE CASCADE" in statement for statement in table_ddl)
    finally:
        engine.dispose()
