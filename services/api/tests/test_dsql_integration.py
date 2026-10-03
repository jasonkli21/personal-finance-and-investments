"""Opt-in checks for a disposable, credentialed Aurora DSQL test cluster.

Set RUN_DSQL_INTEGRATION=1 and DSQL_TEST_CLUSTER=disposable explicitly. These
tests create migration objects and synthetic rows in the selected cluster.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from os import environ
from threading import Event, Thread
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import PositionInput, PositionReplace
from app.config import load_settings
from app.db import dsql_migrations
from app.db.dsql_migrations import (
    DsqlMigration,
    DsqlMigrationStep,
    run_dsql_migrations,
)
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


def test_real_dsql_populated_previous_schema_upgrade() -> None:
    """Upgrade a populated core-only schema to head and retain its source row."""
    migration_engine, app_engine = _open_engines()
    issuer_id = uuid4()
    now = datetime.now(UTC)
    try:
        with migration_engine.connect() as connection:
            if inspect(connection).has_table("dsql_schema_migration_steps"):
                revisions: set[str] = set(
                    connection.execute(
                        text(
                            "SELECT DISTINCT revision FROM dsql_schema_migration_steps"
                        )
                    ).scalars()
                )
                if revisions - {dsql_migrations.CORE_SCHEMA.revision}:
                    pytest.fail(
                        "Use a fresh disposable DSQL cluster for the populated "
                        "previous-schema upgrade case"
                    )
        run_dsql_migrations(migration_engine, (dsql_migrations.CORE_SCHEMA,))
        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO issuers "
                    "(id, normalized_name, display_name, created_at, updated_at) "
                    "VALUES (:id, :normalized, :display, :now, :now)"
                ),
                {
                    "id": issuer_id,
                    "normalized": f"synthetic-upgrade-{issuer_id.hex}",
                    "display": "Synthetic prior-schema issuer",
                    "now": now,
                },
            )
        run_dsql_migrations(migration_engine)
        with migration_engine.connect() as connection:
            row: str = connection.execute(
                text("SELECT display_name FROM issuers WHERE id = :id"),
                {"id": issuer_id},
            ).scalar_one()
            assert row == "Synthetic prior-schema issuer"
    finally:
        with migration_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM issuers WHERE id = :id"), {"id": issuer_id}
            )
        app_engine.dispose()
        migration_engine.dispose()


def test_real_dsql_mid_migration_interruption_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover when DDL committed but its migration-ledger write did not."""
    migration_engine, _app_engine = _open_engines()
    suffix = uuid4().hex[:16]
    table_name = f"stage4_resume_{suffix}"
    revision = f"stage4_resume_{suffix}"
    step = DsqlMigrationStep(
        key="create_resume_table",
        kind="table",
        statement=(
            f"CREATE TABLE {table_name} (id uuid NOT NULL, "
            f"CONSTRAINT {table_name}_pkey PRIMARY KEY (id))"
        ),
        object_name=table_name,
        ready_check="SELECT true",
    )
    migration = DsqlMigration(revision, (step,))
    monkeypatch.setitem(
        dsql_migrations.TABLE_COLUMNS,
        table_name,
        (("id", "uuid", "NO", None, None, None),),
    )
    monkeypatch.setitem(
        dsql_migrations.TABLE_CONSTRAINTS,
        table_name,
        ((f"{table_name}_pkey", "PRIMARY KEY", ("primarykey(id)",)),),
    )
    original_record = dsql_migrations._record_complete
    interrupted = False

    def fail_once(
        engine: Engine, migration_revision: str, migration_step: DsqlMigrationStep
    ) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RuntimeError("synthetic interruption after DDL commit")
        original_record(engine, migration_revision, migration_step)

    monkeypatch.setattr(dsql_migrations, "_record_complete", fail_once)
    try:
        with pytest.raises(RuntimeError, match="after DDL commit"):
            run_dsql_migrations(migration_engine, (migration,))
        monkeypatch.setattr(dsql_migrations, "_record_complete", original_record)
        run_dsql_migrations(migration_engine, (migration,))
        assert dsql_migrations._is_complete(migration_engine, step)
    finally:
        with migration_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        with migration_engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM dsql_schema_migration_steps WHERE revision = :revision"
                ),
                {"revision": revision},
            )
        migration_engine.dispose()


@pytest.mark.skipif(
    environ.get("RUN_DSQL_TOKEN_EXPIRY_TEST") != "1",
    reason="requires explicit opt-in to wait beyond IAM token expiry",
)
def test_real_dsql_application_role_reconnects_after_iam_token_expiry() -> None:
    """Reconnect with a newly generated IAM token after the prior token expires."""
    migration_engine, app_engine = _open_engines()
    try:
        with app_engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
        # Aurora DSQL IAM authentication tokens are valid for 15 minutes.
        sleep(16 * 60)
        app_engine.dispose()
        with app_engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        app_engine.dispose()
        migration_engine.dispose()


def test_real_dsql_migration_and_synthetic_persistence() -> None:
    migration_engine, app_engine = _open_engines()
    issuer_id, account_id, security_id, quote_id, event_id = [uuid4() for _ in range(5)]
    file_id, lot_import_id, lot_row_id, lot_id, adjustment_id = [
        uuid4() for _ in range(5)
    ]
    now = datetime(2026, 10, 1, tzinfo=UTC)
    file_hash = f"{file_id.hex:0<64}"[:64]
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

            connection.execute(
                text(
                    "INSERT INTO investment_events "
                    "(id, account_id, security_id, event_type, effective_date, "
                    "quantity_delta, cash_amount, currency, is_external_flow, "
                    "source_label, source_event_id, evidence_ref, quality_status, "
                    "review_status, idempotency_key, raw_values, created_at, "
                    "updated_at) "
                    "VALUES (:id, :account, :security, 'buy', :date, :quantity, "
                    ":cash, 'USD', false, 'fixture', 'dsql-buy-1', 'page 1', "
                    "'reported', 'reviewed', :key, CAST(:raw AS jsonb), :now, :now)"
                ),
                {
                    "id": event_id,
                    "account": account_id,
                    "security": security_id,
                    "date": date(2026, 1, 2),
                    "quantity": Decimal("0.25"),
                    "cash": Decimal("-30.86"),
                    "key": f"synthetic-event-{event_id}",
                    "raw": '{"quantity":"0.25"}',
                    "now": now,
                },
            )
            saved_event = connection.execute(
                text(
                    "SELECT quantity_delta, cash_amount, is_external_flow, "
                    "raw_values ->> 'quantity' AS quantity FROM investment_events "
                    "WHERE id = :id"
                ),
                {"id": event_id},
            ).one()
            assert saved_event.quantity_delta == Decimal("0.2500000000")
            assert saved_event.cash_amount == Decimal("-30.8600000000")
            assert saved_event.is_external_flow is False
            assert saved_event.quantity == "0.25"

            connection.execute(
                text(
                    "INSERT INTO private_files (id, content_hash, storage_key, "
                    "original_name, content_type, byte_size, created_at, updated_at) "
                    "VALUES (:id, :hash, :key, 'lots.csv', 'text/csv', 64, :now, :now)"
                ),
                {
                    "id": file_id,
                    "hash": file_hash,
                    "key": f"{file_hash}.blob",
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO tax_lot_imports (id, account_id, file_id, "
                    "source_label, parser_version, file_sha256, idempotency_key, "
                    "review_revision, row_count, status, diagnostics, published_at, "
                    "created_at, updated_at) VALUES (:id, :account, :file, "
                    "'fixture', 'tax-lots-csv-v1', :hash, :key, 1, 1, 'published', "
                    "CAST(:diagnostics AS jsonb), :now, :now, :now)"
                ),
                {
                    "id": lot_import_id,
                    "account": account_id,
                    "file": file_id,
                    "hash": file_hash,
                    "key": f"synthetic-lot-import-{lot_import_id}",
                    "diagnostics": '{"fixture":true}',
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO tax_lot_import_rows (id, import_id, row_number, "
                    "raw_payload, raw_ticker, raw_source_lot_id, security_id, "
                    "acquired_at, initial_quantity, remaining_quantity, "
                    "initial_basis, remaining_basis, basis_currency, evidence_ref, "
                    "quality_status, row_status, diagnostics, created_at, updated_at) "
                    "VALUES (:id, :import, 1, CAST(:raw AS jsonb), 'SYN', 'LOT-1', "
                    ":security, :date, :initial_quantity, :remaining_quantity, "
                    ":initial_basis, :remaining_basis, 'USD', 'fixture:line-1', "
                    "'reported', 'published', CAST(:diagnostics AS jsonb), :now, :now)"
                ),
                {
                    "id": lot_row_id,
                    "import": lot_import_id,
                    "security": security_id,
                    "date": date(2020, 1, 2),
                    "initial_quantity": Decimal("1"),
                    "remaining_quantity": Decimal("0.75"),
                    "initial_basis": Decimal("100"),
                    "remaining_basis": Decimal("75"),
                    "raw": '{"Shares":"0.75"}',
                    "diagnostics": "{}",
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO tax_lots (id, account_id, security_id, import_id, "
                    "import_row_id, source_label, source_lot_id, identity_key, "
                    "acquired_at, initial_quantity, remaining_quantity, initial_basis, "
                    "remaining_basis, basis_currency, evidence_ref, quality_status, "
                    "created_at, updated_at) VALUES (:id, :account, :security, "
                    ":import, :row, 'fixture', 'LOT-1', :identity, :date, 1, 0.75, "
                    "100, 75, 'USD', 'fixture:line-1', 'reported', :now, :now)"
                ),
                {
                    "id": lot_id,
                    "account": account_id,
                    "security": security_id,
                    "import": lot_import_id,
                    "row": lot_row_id,
                    "identity": f"{lot_id.hex:0<64}"[:64],
                    "date": date(2020, 1, 2),
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO tax_lot_adjustments (id, tax_lot_id, "
                    "adjustment_type, quantity_delta, basis_delta, basis_currency, "
                    "effective_date, source_label, reason, evidence_ref, "
                    "idempotency_key, raw_values, created_at) VALUES (:id, :lot, "
                    "'correction', -0.05, -5, 'USD', :date, 'fixture', 'synthetic "
                    "correction', 'fixture:line-2', :key, CAST(:raw AS jsonb), :now)"
                ),
                {
                    "id": adjustment_id,
                    "lot": lot_id,
                    "date": date(2026, 1, 2),
                    "key": f"synthetic-lot-adjustment-{adjustment_id}",
                    "raw": '{"adjustment":"synthetic"}',
                    "now": now,
                },
            )
            saved_lot = connection.execute(
                text(
                    "SELECT l.remaining_quantity + a.quantity_delta AS quantity, "
                    "l.remaining_basis + a.basis_delta AS basis, "
                    "r.raw_payload ->> 'Shares' AS raw_quantity "
                    "FROM tax_lots l JOIN tax_lot_adjustments a "
                    "ON a.tax_lot_id = l.id JOIN tax_lot_import_rows r "
                    "ON r.id = l.import_row_id WHERE l.id = :id"
                ),
                {"id": lot_id},
            ).one()
            assert saved_lot.quantity == Decimal("0.7000000000")
            assert saved_lot.basis == Decimal("70.0000000000")
            assert saved_lot.raw_quantity == "0.75"

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
                    text("DELETE FROM tax_lot_adjustments WHERE id = :id"),
                    {"id": adjustment_id},
                )
                connection.execute(
                    text("DELETE FROM tax_lots WHERE id = :id"), {"id": lot_id}
                )
                connection.execute(
                    text("DELETE FROM tax_lot_import_rows WHERE id = :id"),
                    {"id": lot_row_id},
                )
                connection.execute(
                    text("DELETE FROM tax_lot_imports WHERE id = :id"),
                    {"id": lot_import_id},
                )
                connection.execute(
                    text("DELETE FROM private_files WHERE id = :id"), {"id": file_id}
                )
                connection.execute(
                    text("DELETE FROM investment_events WHERE id = :id"),
                    {"id": event_id},
                )
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


def test_real_dsql_auth_schema_and_session_round_trip() -> None:
    """Use the scoped app role against the new auth/audit schema and constraints."""
    migration_engine, app_engine = _open_engines()
    run_dsql_migrations(migration_engine)
    migration_engine.dispose()
    principal_id, session_id, audit_id = [uuid4() for _ in range(3)]
    now = datetime.now(UTC)
    issuer = "https://synthetic.example.invalid/"
    subject = f"synthetic-{principal_id}"
    scope_id = f"synthetic-{principal_id.hex}"
    token_hash = f"{session_id.hex:0<64}"[:64]
    try:
        with app_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO auth_principals "
                    "(id, issuer, subject, scope_id, active, created_at) "
                    "VALUES (:id, :issuer, :subject, :scope, true, :now)"
                ),
                {
                    "id": principal_id,
                    "issuer": issuer,
                    "subject": subject,
                    "scope": scope_id,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(id, principal_id, token_hash, created_at, expires_at) "
                    "VALUES (:id, :principal, :hash, :now, :expires)"
                ),
                {
                    "id": session_id,
                    "principal": principal_id,
                    "hash": token_hash,
                    "now": now,
                    "expires": now.replace(year=now.year + 1),
                },
            )
            connection.execute(
                text(
                    "INSERT INTO security_audit_events "
                    "(id, actor_subject, scope_id, action, target_type, target_id, "
                    "result, correlation_id, created_at) VALUES (:id, :subject, "
                    ":scope, 'login', 'session', :target, 'success', :correlation, "
                    ":now)"
                ),
                {
                    "id": audit_id,
                    "subject": subject,
                    "scope": scope_id,
                    "target": str(session_id),
                    "correlation": str(uuid4()),
                    "now": now,
                },
            )
        with app_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT p.issuer, p.subject, p.scope_id, s.token_hash, "
                    "s.revoked_at, a.action, a.result FROM auth_principals p "
                    "JOIN auth_sessions s ON s.principal_id = p.id "
                    "JOIN security_audit_events a ON a.scope_id = p.scope_id "
                    "WHERE p.id = :id AND s.id = :session AND a.id = :audit"
                ),
                {"id": principal_id, "session": session_id, "audit": audit_id},
            ).one()
            assert row.issuer == issuer
            assert row.subject == subject
            assert row.scope_id == scope_id
            assert row.token_hash == token_hash
            assert row.revoked_at is None
            assert row.action == "login"
            assert row.result == "success"

        # Unique principal and session identities must be enforced by the
        # deployed schema, with each expected violation isolated to its own txn.
        with pytest.raises(SQLAlchemyError) as duplicate_principal:
            with app_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO auth_principals "
                        "(id, issuer, subject, scope_id, active, created_at) "
                        "VALUES (:id, :issuer, :subject, :scope, true, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "issuer": issuer,
                        "subject": subject,
                        "scope": f"duplicate-{principal_id.hex}",
                        "now": now,
                    },
                )
        assert (
            getattr(getattr(duplicate_principal.value, "orig", None), "sqlstate", None)
            == "23505"
        )
        with pytest.raises(SQLAlchemyError) as duplicate_session:
            with app_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO auth_sessions "
                        "(id, principal_id, token_hash, created_at, expires_at) "
                        "VALUES (:id, :principal, :hash, :now, :expires)"
                    ),
                    {
                        "id": uuid4(),
                        "principal": principal_id,
                        "hash": token_hash,
                        "now": now,
                        "expires": now.replace(year=now.year + 1),
                    },
                )
        assert (
            getattr(getattr(duplicate_session.value, "orig", None), "sqlstate", None)
            == "23505"
        )
    finally:
        with app_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM security_audit_events WHERE id = :id"),
                {"id": audit_id},
            )
            connection.execute(
                text("DELETE FROM auth_sessions WHERE id = :id"),
                {"id": session_id},
            )
            connection.execute(
                text("DELETE FROM auth_principals WHERE id = :id"),
                {"id": principal_id},
            )
        app_engine.dispose()


def test_real_dsql_application_role_reconnects_with_verified_tls() -> None:
    """Dispose the pool and prove the scoped role can open a fresh IAM connection."""
    migration_engine, app_engine = _open_engines()
    run_dsql_migrations(migration_engine)
    migration_engine.dispose()
    try:
        with app_engine.connect() as connection:
            current_user: str = connection.execute(
                text("SELECT current_user")
            ).scalar_one()
            assert current_user == load_settings().aurora_dsql_db_user
        app_engine.dispose()

        reconnect_migration_engine, reconnected_engine = _open_engines()
        reconnect_migration_engine.dispose()
        try:
            with reconnected_engine.connect() as connection:
                reconnected_user: str = connection.execute(
                    text("SELECT current_user")
                ).scalar_one()
            assert reconnected_user == load_settings().aurora_dsql_db_user
        finally:
            reconnected_engine.dispose()
    finally:
        app_engine.dispose()
