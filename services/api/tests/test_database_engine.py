"""Standard psycopg engine, direct migration endpoint and bounded pool."""

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.db.models import Base


def test_runtime_and_migration_urls_use_psycopg_and_preserve_credentials() -> None:
    settings = replace(
        load_settings(),
        database_url="postgresql://app:p%40ss@pooled.example/db",
        migration_database_url="postgresql://migrator:direct@direct.example/db",
    )
    app = DatabaseEngineFactory.create(settings)
    migration = DatabaseEngineFactory.create(settings, purpose="migration")
    try:
        assert app.url.drivername == migration.url.drivername == "postgresql+psycopg"
        assert app.url.password == "p@ss"
        assert app.url.host == "pooled.example"
        assert migration.url.username == "migrator"
        assert migration.url.host == "direct.example"
        assert isinstance(app.pool, QueuePool)
        assert app.pool.size() == settings.database_pool_size
        assert app.pool._pre_ping is True
    finally:
        app.dispose()
        migration.dispose()


def test_postgres_compiles_full_schema_without_connecting() -> None:
    engine = create_engine("postgresql+psycopg://localhost/compile")
    try:
        tables = [
            str(CreateTable(t).compile(dialect=engine.dialect))
            for t in Base.metadata.sorted_tables
        ]
        indexes = [
            str(CreateIndex(i).compile(dialect=engine.dialect))
            for t in Base.metadata.sorted_tables
            for i in t.indexes
        ]
        assert len(tables) == 45
        assert len(indexes) == 35
        assert all(s.startswith("CREATE INDEX") for s in indexes)
        assert any("JSONB" in s for s in tables)
        assert any("NUMERIC(28, 10)" in s for s in tables)
    finally:
        engine.dispose()


@pytest.mark.parametrize("url", ["", "postgresql://synthetic@localhost/db"])
def test_alembic_production_never_falls_back_to_local_or_unverified_tls(
    url: str,
) -> None:
    environment = dict(os.environ)
    environment.update(
        APP_ENV="Production", DATABASE_URL=url, MIGRATION_DATABASE_URL=""
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "CREATE TABLE" not in result.stdout
    assert (
        "Production migrations require" if not url else "verify-full"
    ) in result.stderr
