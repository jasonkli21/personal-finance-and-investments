"""Opt-in checks for a disposable, credentialed Aurora DSQL test cluster.

Set RUN_DSQL_INTEGRATION=1 and DSQL_TEST_CLUSTER=disposable explicitly. These
tests create migration objects and synthetic rows in the selected cluster.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from os import environ
from threading import Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings
from app.db.dsql_migrations import run_dsql_migrations
from app.db.engine import DatabaseEngineFactory
from app.db.transactions import run_database_unit

pytestmark = pytest.mark.skipif(
    environ.get("RUN_DSQL_INTEGRATION") != "1"
    or environ.get("DSQL_TEST_CLUSTER") != "disposable",
    reason="requires explicit opt-in and a disposable Aurora DSQL cluster",
)


def _open_engines() -> tuple[Engine, Engine]:
    settings = load_settings()
    if settings.database_backend != "aurora_dsql":
        pytest.fail("Set DATABASE_BACKEND=aurora_dsql for the DSQL integration suite")
    migration_engine = DatabaseEngineFactory.create(settings, purpose="migration")
    app_engine = DatabaseEngineFactory.create(settings, purpose="application")
    return migration_engine, app_engine


def test_real_dsql_migration_and_synthetic_persistence() -> None:
    migration_engine, app_engine = _open_engines()
    issuer_id, account_id, security_id, quote_id = [uuid4() for _ in range(4)]
    now = datetime(2026, 10, 1, tzinfo=UTC)
    schema_ready = False
    try:
        run_dsql_migrations(migration_engine)
        schema_ready = True
        with app_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO issuers (id, normalized_name, display_name, "
                    "created_at, updated_at) VALUES (:id, :normalized, "
                    ":display, :now, :now)"
                ),
                {
                    "id": issuer_id,
                    "normalized": f"synthetic dsql {issuer_id}",
                    "display": "Synthetic DSQL Issuer",
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, name, account_type, base_currency, "
                    "active, source_type, created_at, updated_at) VALUES "
                    "(:id, 'Synthetic DSQL', 'taxable', 'USD', true, 'fixture', "
                    ":now, :now)"
                ),
                {"id": account_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO securities (id, security_type, display_ticker, "
                    "name, issuer_id, currency, created_at, updated_at) VALUES "
                    "(:id, 'equity', 'SYN', 'Synthetic DSQL Security', :issuer, "
                    "'USD', :now, :now)"
                ),
                {"id": security_id, "issuer": issuer_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO quotes (id, security_id, as_of, price, currency, "
                    "source, fetched_at, quality_status, provider_metadata, "
                    "created_at, updated_at) VALUES (:id, :security, :now, :price, "
                    "'USD', 'fixture', :now, 'reported', CAST(:metadata AS jsonb), "
                    ":now, :now)"
                ),
                {
                    "id": quote_id,
                    "security": security_id,
                    "now": now,
                    "price": Decimal("123.4567890123"),
                    "metadata": '{"kind":"synthetic"}',
                },
            )
            saved = connection.execute(
                text(
                    "SELECT q.id, q.price, q.provider_metadata ->> 'kind' AS kind "
                    "FROM quotes q WHERE q.id = :id"
                ),
                {"id": quote_id},
            ).one()
            assert saved.id == quote_id
            assert saved.price == Decimal("123.4567890123")
            assert saved.kind == "synthetic"

        with pytest.raises(SQLAlchemyError):
            with app_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO securities (id, security_type, name, issuer_id, "
                        "currency, created_at, updated_at) VALUES (:id, 'equity', "
                        "'Invalid synthetic', :issuer, 'USD', :now, :now)"
                    ),
                    {"id": uuid4(), "issuer": uuid4(), "now": now},
                )
    finally:
        if schema_ready:
            with app_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM quotes WHERE id = :id"), {"id": quote_id}
                )
                connection.execute(
                    text("DELETE FROM securities WHERE id = :id"),
                    {"id": security_id},
                )
                connection.execute(
                    text("DELETE FROM accounts WHERE id = :id"), {"id": account_id}
                )
                connection.execute(
                    text("DELETE FROM issuers WHERE id = :id"), {"id": issuer_id}
                )
        migration_engine.dispose()
        app_engine.dispose()


def test_real_dsql_occ_conflict_uses_bounded_database_retry() -> None:
    migration_engine, app_engine = _open_engines()
    run_dsql_migrations(migration_engine)
    migration_engine.dispose()
    sessions = sessionmaker(app_engine, expire_on_commit=False)
    account_id = uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    with app_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts (id, name, account_type, base_currency, active, "
                "source_type, created_at, updated_at) VALUES (:id, 'Synthetic OCC', "
                "'taxable', 'USD', true, 'fixture', :now, :now)"
            ),
            {"id": account_id, "now": now},
        )

    competitor_finished = Event()
    competitor_errors: list[BaseException] = []
    competing_write_count = 0

    def competing_write() -> None:
        nonlocal competing_write_count
        try:
            with sessions() as session, session.begin():
                session.execute(
                    text(
                        "UPDATE accounts SET name = 'Synthetic competitor' "
                        "WHERE id = :id"
                    ),
                    {"id": account_id},
                )
            competing_write_count += 1
        except BaseException as exc:  # surfaced in the parent test thread below
            competitor_errors.append(exc)
        finally:
            competitor_finished.set()

    attempts = 0
    external_call_count = 0

    def external_call() -> None:
        nonlocal external_call_count
        external_call_count += 1

    external_call()
    competitor: Thread | None = None

    def conflicted_write(session: Session) -> None:
        nonlocal attempts, competitor
        attempts += 1
        session.execute(
            text("SELECT name FROM accounts WHERE id = :id"), {"id": account_id}
        ).one()
        if attempts == 1:
            competitor = Thread(target=competing_write, daemon=True)
            competitor.start()
            if not competitor_finished.wait(timeout=20):
                raise TimeoutError("competing DSQL transaction did not finish")
            if competitor_errors:
                raise competitor_errors[0]
        session.execute(
            text("UPDATE accounts SET name = 'Synthetic retried' WHERE id = :id"),
            {"id": account_id},
        )

    try:
        run_database_unit(sessions, conflicted_write)
        if competitor is not None:
            competitor.join(timeout=20)
        assert attempts == 2
        assert competing_write_count == 1
        assert external_call_count == 1
        with app_engine.connect() as connection:
            name: str = connection.execute(
                text("SELECT name FROM accounts WHERE id = :id"),
                {"id": account_id},
            ).scalar_one()
        assert name == "Synthetic retried"
    finally:
        if competitor is not None:
            competitor.join(timeout=20)
        with app_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM accounts WHERE id = :id"), {"id": account_id}
            )
        app_engine.dispose()
