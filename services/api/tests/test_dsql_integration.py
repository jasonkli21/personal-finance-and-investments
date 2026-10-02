"""Opt-in checks for a disposable, credentialed Aurora DSQL test cluster.

Set RUN_DSQL_INTEGRATION=1 and DSQL_TEST_CLUSTER=disposable explicitly. These
tests create migration objects and synthetic rows in the selected cluster.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from os import environ
from threading import Event, Thread
from uuid import uuid4

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import PositionInput, PositionReplace
from app.config import load_settings
from app.db.dsql_migrations import run_dsql_migrations
from app.db.engine import DatabaseEngineFactory
from app.db.transactions import run_database_unit
from app.domains import portfolio

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


def test_real_dsql_manual_replacement_history_and_scoped_identity() -> None:
    """Exercise append-only replacement and scoped identities on a live cluster."""
    migration_engine, app_engine = _open_engines()
    run_dsql_migrations(migration_engine)
    migration_engine.dispose()
    sessions = sessionmaker(app_engine, expire_on_commit=False)
    issuer_a, issuer_b, account_id, security_id = [uuid4() for _ in range(4)]
    first_snapshot_id: object | None = None
    try:
        now = datetime(2026, 10, 1, tzinfo=UTC)
        with app_engine.begin() as connection:
            for issuer_id, name in (
                (issuer_a, "dsql scope a"),
                (issuer_b, "dsql scope b"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO issuers (id, normalized_name, display_name, "
                        "created_at, updated_at) "
                        "VALUES (:id, :name, :name, :now, :now)"
                    ),
                    {"id": issuer_id, "name": name, "now": now},
                )
            connection.execute(
                text(
                    "INSERT INTO issuer_aliases (id, issuer_id, alias, "
                    "normalized_alias, "
                    "alias_namespace, source, review_status) VALUES (:id, :issuer, "
                    "'Shared DSQL Name', 'shared dsql name', 'name', 'fixture', "
                    "'unreviewed')"
                ),
                {"id": uuid4(), "issuer": issuer_a},
            )
            connection.execute(
                text(
                    "INSERT INTO issuer_aliases (id, issuer_id, alias, "
                    "normalized_alias, "
                    "alias_namespace, source, review_status) VALUES (:id, :issuer, "
                    "'Shared DSQL Name', 'shared dsql name', 'name', 'fixture', "
                    "'needs_review')"
                ),
                {"id": uuid4(), "issuer": issuer_b},
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, name, account_type, base_currency, "
                    "active, "
                    "source_type, created_at, updated_at) VALUES (:id, 'Synthetic DSQL "
                    "Revision', 'taxable', 'USD', true, 'fixture', :now, :now)"
                ),
                {"id": account_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO securities (id, security_type, display_ticker, "
                    "name, issuer_id, "
                    "currency, created_at, updated_at) VALUES (:id, 'equity', 'SDQ', "
                    "'Synthetic DSQL Revision Security', :issuer, 'USD', :now, :now)"
                ),
                {"id": security_id, "issuer": issuer_a, "now": now},
            )
            for exchange in ("NYSE", "NASDAQ"):
                connection.execute(
                    text(
                        "INSERT INTO security_identifiers (id, security_id, "
                        "namespace, exchange, "
                        "value, normalized_value, valid_from, source, review_status) "
                        "VALUES (:id, :security, 'ticker', :exchange, 'SDQ', 'sdq', "
                        ":valid_from, 'fixture', 'reviewed')"
                    ),
                    {
                        "id": uuid4(),
                        "security": security_id,
                        "exchange": exchange,
                        "valid_from": date(2020, 1, 1),
                    },
                )
            alias_count: int = connection.execute(
                text(
                    "SELECT count(*) FROM issuer_aliases WHERE normalized_alias = "
                    "'shared dsql name' AND alias_namespace = 'name'"
                )
            ).scalar_one()
            assert alias_count == 2

        # DSQL does not rely on PostgreSQL savepoints: isolate the expected
        # uniqueness failure in its own transaction and let it roll back.
        with pytest.raises(SQLAlchemyError):
            with app_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO security_identifiers (id, security_id, "
                        "namespace, exchange, "
                        "value, normalized_value, valid_from, source, review_status) "
                        "VALUES (:id, :security, 'ticker', 'NYSE', 'SDQ', 'sdq', "
                        ":valid_from, 'fixture', 'reviewed')"
                    ),
                    {
                        "id": uuid4(),
                        "security": security_id,
                        "valid_from": date(2020, 1, 1),
                    },
                )

        first = run_database_unit(
            sessions,
            lambda session: portfolio.replace_positions(
                session,
                account_id,
                PositionReplace(
                    expected_revision=None,
                    effective_date=date(2026, 10, 1),
                    positions=[
                        PositionInput(
                            security_id=security_id,
                            quantity="2",
                            reported_price="10",
                            currency="USD",
                        )
                    ],
                ),
            ),
        )
        first_snapshot_id = first.id
        second = run_database_unit(
            sessions,
            lambda session: portfolio.replace_positions(
                session,
                account_id,
                PositionReplace(
                    expected_revision=1,
                    effective_date=date(2026, 10, 1),
                    positions=[
                        PositionInput(
                            security_id=security_id,
                            quantity="3",
                            reported_price="11",
                            currency="USD",
                        )
                    ],
                ),
            ),
        )
        assert first.id != second.id
        assert first.revision == 1 and second.revision == 2

        def replace_then_abort(session: Session) -> None:
            portfolio.replace_positions(
                session,
                account_id,
                PositionReplace(
                    expected_revision=2,
                    effective_date=date(2026, 10, 1),
                    positions=[
                        PositionInput(
                            security_id=security_id,
                            quantity="99",
                            reported_price="11",
                            currency="USD",
                        )
                    ],
                ),
            )
            raise RuntimeError("synthetic rollback")

        with pytest.raises(RuntimeError, match="synthetic rollback"):
            run_database_unit(sessions, replace_then_abort)

        with app_engine.connect() as connection:
            state = connection.execute(
                text(
                    "SELECT a.current_position_revision, "
                    "a.current_position_snapshot_id, "
                    "p.status, l.quantity FROM accounts a JOIN position_snapshots p "
                    "ON p.id = a.current_position_snapshot_id "
                    "JOIN position_snapshot_lines l "
                    "ON l.snapshot_id = p.id WHERE a.id = :id"
                ),
                {"id": account_id},
            ).one()
            assert state.current_position_revision == 2
            assert state.status == "accepted"
            assert state.quantity == Decimal("3.0000000000")
            retained: int = connection.execute(
                text(
                    "SELECT count(*) FROM position_snapshot_lines "
                    "WHERE snapshot_id = :id"
                ),
                {"id": first_snapshot_id},
            ).scalar_one()
            assert retained == 1
    finally:
        with app_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE accounts SET current_position_snapshot_id = NULL "
                    "WHERE id = :id"
                ),
                {"id": account_id},
            )
            connection.execute(
                text(
                    "DELETE FROM position_snapshot_lines WHERE snapshot_id IN "
                    "(SELECT id FROM position_snapshots WHERE account_id = :id)"
                ),
                {"id": account_id},
            )
            connection.execute(
                text("DELETE FROM position_snapshots WHERE account_id = :id"),
                {"id": account_id},
            )
            connection.execute(
                text("DELETE FROM accounts WHERE id = :id"), {"id": account_id}
            )
            connection.execute(
                text("DELETE FROM security_identifiers WHERE security_id = :id"),
                {"id": security_id},
            )
            connection.execute(
                text("DELETE FROM securities WHERE id = :id"), {"id": security_id}
            )
            connection.execute(
                text("DELETE FROM issuer_aliases WHERE issuer_id IN (:first, :second)"),
                {"first": issuer_a, "second": issuer_b},
            )
            connection.execute(
                text("DELETE FROM issuers WHERE id IN (:first, :second)"),
                {"first": issuer_a, "second": issuer_b},
            )
        app_engine.dispose()
