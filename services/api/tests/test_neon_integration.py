"""Explicit disposable Neon gate; no local result substitutes for these tests."""

import os

import pytest
from sqlalchemy import Engine, create_engine, text
from test_core_schema import _migrate, _reset_schema
from test_core_schema import (
    test_populated_0002_upgrade_reconciles_revisions_and_preserves_manual_history as verify_upgrade,  # noqa: E501
)
from test_transactions import verify_actual_serialization_retry

from app.db.urls import postgres_url

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_NEON_INTEGRATION") != "1"
    or os.environ.get("NEON_TEST_DATABASE") != "disposable",
    reason="Explicit disposable Neon credentials required",
)


def _open_engines() -> tuple[Engine, Engine]:
    # Both are validated before any destructive reset. Use a dedicated branch,
    # never the production database. DDL may use a separate migration identity.
    runtime = postgres_url(os.environ["NEON_TEST_DATABASE_URL"], production=True)
    migration = postgres_url(
        os.environ["NEON_TEST_MIGRATION_DATABASE_URL"], production=True
    )
    if (
        "-pooler" in (migration.host or "")
        or runtime.database != migration.database
        or (runtime.host or "").replace("-pooler", "") != migration.host
    ):
        raise ValueError(
            "Neon test runtime and migration endpoints must target the same branch"
        )
    return create_engine(migration), create_engine(
        runtime, pool_pre_ping=True, pool_size=2, max_overflow=0
    )


def test_real_neon_fresh_alembic_schema() -> None:
    migration, runtime = _open_engines()
    try:
        _reset_schema(migration)
        _migrate(os.environ["NEON_TEST_MIGRATION_DATABASE_URL"])
        with runtime.connect() as conn:
            assert (
                conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_type='BASE TABLE'"
                    )
                )
                == 46
            )
    finally:
        migration.dispose()
        runtime.dispose()


def test_real_neon_populated_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    migration, runtime = _open_engines()
    migration.dispose()
    runtime.dispose()
    monkeypatch.setenv(
        "TEST_DATABASE_URL", os.environ["NEON_TEST_MIGRATION_DATABASE_URL"]
    )
    monkeypatch.delenv("MIGRATION_DATABASE_URL", raising=False)
    verify_upgrade()


def test_real_neon_reconnect() -> None:
    migration, runtime = _open_engines()
    try:
        with runtime.connect() as conn:
            assert conn.scalar(text("SELECT 1")) == 1
        runtime.dispose()
        with runtime.connect() as conn:
            assert conn.scalar(text("SELECT 1")) == 1
    finally:
        migration.dispose()
        runtime.dispose()


def test_real_neon_transaction_retry() -> None:
    migration, runtime = _open_engines()
    try:
        verify_actual_serialization_retry(runtime)
    finally:
        migration.dispose()
        runtime.dispose()
