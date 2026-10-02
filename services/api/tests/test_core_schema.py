"""Core schema integration coverage; set TEST_DATABASE_URL to a disposable PG16 DB."""

import subprocess
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from os import environ
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


def _migrate(database_url: str, revision: str = "head") -> None:
    api_dir = Path(__file__).parents[1]
    migration_env = environ.copy()
    migration_env["DATABASE_URL"] = database_url
    migration_env["DATABASE_BACKEND"] = "postgres"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=api_dir,
        env=migration_env,
        check=True,
        capture_output=True,
        text=True,
    )


def _reset_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


def test_core_schema_migration_and_round_trip() -> None:
    database_url = environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL 16 database")

    engine = create_engine(database_url)
    _reset_schema(engine)
    _migrate(database_url)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    issuer_id, security_id, account_id, snapshot_id = [uuid4() for _ in range(4)]
    normalized_name = f"synthetic {issuer_id}"
    with engine.connect() as connection, connection.begin_nested():
        connection.execute(
            text(
                "INSERT INTO issuers (id, normalized_name, "
                "display_name, created_at, updated_at) "
                "VALUES (:id, :normalized_name, 'Synthetic Inc.', :now, :now)"
            ),
            {"id": issuer_id, "normalized_name": normalized_name, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO issuer_aliases (id, issuer_id, alias, "
                "normalized_alias, source) "
                "VALUES (:id, :issuer_id, 'ACME Corp', 'acme corp', 'fixture')"
            ),
            {"id": uuid4(), "issuer_id": issuer_id},
        )
        connection.execute(
            text(
                "INSERT INTO securities "
                "(id, security_type, display_ticker, name, issuer_id, "
                "currency, created_at, updated_at) "
                "VALUES (:id, 'equity', 'ACME', 'Acme Inc.', "
                ":issuer_id, 'USD', :now, :now)"
            ),
            {"id": security_id, "issuer_id": issuer_id, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO accounts "
                "(id, name, account_type, base_currency, active, "
                "source_type, created_at, updated_at) "
                "VALUES (:id, 'Synthetic Brokerage', 'taxable', 'USD', "
                "true, 'manual', :now, :now)"
            ),
            {"id": account_id, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO position_snapshots "
                "(id, account_id, snapshot_at, source, status, "
                "accepted_at, created_at, updated_at) "
                "VALUES (:id, :account_id, :now, 'fixture', "
                "'accepted', :now, :now, :now)"
            ),
            {"id": snapshot_id, "account_id": account_id, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO position_snapshot_lines "
                "(id, snapshot_id, security_id, quantity, "
                "reported_value, reported_price, "
                "currency, source, quality_status) "
                "VALUES (:id, :snapshot_id, :security_id, :quantity, "
                ":value, :price, 'USD', "
                "'fixture', 'reported')"
            ),
            {
                "id": uuid4(),
                "snapshot_id": snapshot_id,
                "security_id": security_id,
                "quantity": Decimal("1.2500000000"),
                "value": Decimal("123.4500000000"),
                "price": Decimal("98.7600000000"),
            },
        )
        connection.execute(
            text(
                "INSERT INTO quotes "
                "(id, security_id, as_of, price, currency, source, "
                "fetched_at, quality_status, "
                "provider_metadata, created_at, updated_at) "
                "VALUES (:id, :security_id, :now, :price, 'USD', "
                "'fixture', :now, 'reported', "
                "CAST('{\"fixture\": true}' AS jsonb), :now, :now)"
            ),
            {
                "id": uuid4(),
                "security_id": security_id,
                "now": now,
                "price": Decimal("98.7654321000"),
            },
        )

        row = connection.execute(
            text(
                "SELECT q.price, p.quantity, q.provider_metadata ->> "
                "'fixture' AS fixture "
                "FROM quotes q JOIN position_snapshot_lines p ON "
                "p.security_id = q.security_id "
                "WHERE q.security_id = :security_id"
            ),
            {"security_id": security_id},
        ).one()
        assert row.price == Decimal("98.7654321000")
        assert row.quantity == Decimal("1.2500000000")
        assert row.fixture == "true"

        event_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO investment_events "
                "(id, account_id, security_id, event_type, effective_date, "
                "quantity_delta, cash_amount, currency, is_external_flow, "
                "source_label, source_event_id, evidence_ref, quality_status, "
                "review_status, idempotency_key, raw_values, created_at, updated_at) "
                "VALUES (:id, :account_id, :security_id, 'buy', :effective_date, "
                ":quantity_delta, :cash_amount, 'USD', false, 'fixture', 'buy-1', "
                "'synthetic statement / page 1', 'reported', 'reviewed', :key, "
                'CAST(\'{"raw_quantity":"0.25"}\' AS jsonb), :now, :now)'
            ),
            {
                "id": event_id,
                "account_id": account_id,
                "security_id": security_id,
                "effective_date": date(2026, 1, 2),
                "quantity_delta": Decimal("0.2500000000"),
                "cash_amount": Decimal("-24.6900000000"),
                "key": f"synthetic-event-{event_id}",
                "now": now,
            },
        )
        event = connection.execute(
            text(
                "SELECT event_type, quantity_delta, cash_amount, is_external_flow, "
                "raw_values ->> 'raw_quantity' AS raw_quantity "
                "FROM investment_events WHERE id = :id"
            ),
            {"id": event_id},
        ).one()
        assert event.event_type == "buy"
        assert event.quantity_delta == Decimal("0.2500000000")
        assert event.cash_amount == Decimal("-24.6900000000")
        assert event.is_external_flow is False
        assert event.raw_quantity == "0.25"

        file_id, lot_import_id, lot_row_id, lot_id, adjustment_id = [
            uuid4() for _ in range(5)
        ]
        file_hash = f"{file_id.hex:0<64}"[:64]
        connection.execute(
            text(
                "INSERT INTO private_files (id, content_hash, storage_key, "
                "original_name, content_type, byte_size, created_at, updated_at) "
                "VALUES (:id, :hash, :key, 'lots.csv', 'text/csv', 64, :now, :now)"
            ),
            {"id": file_id, "hash": file_hash, "key": f"{file_hash}.blob", "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO tax_lot_imports (id, account_id, file_id, source_label, "
                "parser_version, file_sha256, idempotency_key, review_revision, "
                "row_count, status, diagnostics, published_at, created_at, updated_at) "
                "VALUES (:id, :account, :file, 'fixture', 'tax-lots-csv-v1', :hash, "
                ":key, 1, 1, 'published', '{}'::jsonb, :now, :now, :now)"
            ),
            {
                "id": lot_import_id,
                "account": account_id,
                "file": file_id,
                "hash": file_hash,
                "key": f"synthetic-tax-lot-import-{lot_import_id}",
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO tax_lot_import_rows (id, import_id, row_number, "
                "raw_payload, raw_ticker, raw_source_lot_id, security_id, acquired_at, "
                "initial_quantity, remaining_quantity, initial_basis, remaining_basis, "
                "basis_currency, evidence_ref, quality_status, row_status, "
                "diagnostics, "
                "created_at, updated_at) VALUES (:id, :import, 1, CAST(:raw AS jsonb), "
                "'ACME', 'LOT-1', :security, :date, 1.25, 1.0, 123.45, 98.76, 'USD', "
                "'fixture:line-1', 'reported', 'published', '{}'::jsonb, :now, :now)"
            ),
            {
                "id": lot_row_id,
                "import": lot_import_id,
                "security": security_id,
                "date": date(2020, 2, 3),
                "raw": '{"Shares":"1.0"}',
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO tax_lots (id, account_id, security_id, import_id, "
                "import_row_id, source_label, source_lot_id, identity_key, "
                "acquired_at, "
                "initial_quantity, remaining_quantity, initial_basis, remaining_basis, "
                "basis_currency, evidence_ref, quality_status, created_at, updated_at) "
                "VALUES (:id, :account, :security, :import, :row, 'fixture', 'LOT-1', "
                ":identity, :date, 1.25, 1.0, 123.45, 98.76, 'USD', 'fixture:line-1', "
                "'reported', :now, :now)"
            ),
            {
                "id": lot_id,
                "account": account_id,
                "security": security_id,
                "import": lot_import_id,
                "row": lot_row_id,
                "identity": f"{lot_id.hex:0<64}"[:64],
                "date": date(2020, 2, 3),
                "now": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO tax_lot_adjustments (id, tax_lot_id, adjustment_type, "
                "quantity_delta, basis_delta, basis_currency, effective_date, "
                "source_label, reason, evidence_ref, idempotency_key, raw_values, "
                "created_at) VALUES (:id, :lot, 'correction', -0.25, -24.69, 'USD', "
                ":date, 'fixture', 'synthetic partial disposition', 'fixture:line-2', "
                ":key, '{}'::jsonb, :now)"
            ),
            {
                "id": adjustment_id,
                "lot": lot_id,
                "date": date(2026, 1, 2),
                "key": f"synthetic-tax-lot-adjustment-{adjustment_id}",
                "now": now,
            },
        )
        saved_lot = connection.execute(
            text(
                "SELECT l.remaining_quantity + a.quantity_delta AS quantity, "
                "l.remaining_basis + a.basis_delta AS basis, "
                "r.raw_payload ->> 'Shares' AS raw_quantity FROM tax_lots l "
                "JOIN tax_lot_adjustments a ON a.tax_lot_id = l.id "
                "JOIN tax_lot_import_rows r ON r.id = l.import_row_id "
                "WHERE l.id = :id"
            ),
            {"id": lot_id},
        ).one()
        assert saved_lot.quantity == Decimal("0.7500000000")
        assert saved_lot.basis == Decimal("74.0700000000")
        assert saved_lot.raw_quantity == "1.0"

        snapshot_revision = connection.execute(
            text(
                "SELECT a.current_position_revision, p.revision "
                "FROM accounts a JOIN position_snapshots p "
                "ON p.account_id = a.id WHERE a.id = :account_id"
            ),
            {"account_id": account_id},
        ).one()
        assert snapshot_revision.current_position_revision == 0
        assert snapshot_revision.revision == 1

        # Preserve source rows with no resolved security and unusual quantities.
        unresolved_id = uuid4()
        connection.execute(
            text(
                "INSERT INTO position_snapshot_lines "
                "(id, snapshot_id, unresolved_ref, quantity, reported_value, currency, "
                "source, quality_status) "
                "VALUES (:id, :snapshot_id, 'RAW: unknown', :quantity, :value, 'USD', "
                "'fixture', 'needs_review')"
            ),
            {
                "id": unresolved_id,
                "snapshot_id": snapshot_id,
                "quantity": Decimal("-0.5000000000"),
                "value": Decimal("0"),
            },
        )
        unresolved = connection.execute(
            text(
                "SELECT unresolved_ref, quantity, reported_value "
                "FROM position_snapshot_lines WHERE id = :id"
            ),
            {"id": unresolved_id},
        ).one()
        assert unresolved.unresolved_ref == "RAW: unknown"
        assert unresolved.quantity == Decimal("-0.5000000000")
        assert unresolved.reported_value == Decimal("0E-10")

        # A per-account/source revision is unique while the same date can be
        # retained in multiple immutable published revisions.
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO position_snapshots "
                        "(id, account_id, snapshot_at, source, status, "
                        "created_at, updated_at) "
                        "VALUES (:id, :account_id, :now, 'fixture', "
                        "'accepted', :now, :now)"
                    ),
                    {"id": uuid4(), "account_id": account_id, "now": now},
                )

        # Foreign keys reject dangling quote references.
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO quotes "
                        "(id, security_id, as_of, price, currency, source, fetched_at, "
                        "quality_status, provider_metadata, created_at, updated_at) "
                        "VALUES (:id, :security_id, :now, 1, 'USD', 'fixture', :now, "
                        "'reported', '{}'::jsonb, :now, :now)"
                    ),
                    {"id": uuid4(), "security_id": uuid4(), "now": now},
                )

        # Quote identity is unique at security + timestamp + source granularity.
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO quotes "
                        "(id, security_id, as_of, price, currency, source, fetched_at, "
                        "quality_status, provider_metadata, created_at, updated_at) "
                        "VALUES (:id, :security_id, :now, 98, 'USD', 'fixture', :now, "
                        "'reported', '{}'::jsonb, :now, :now)"
                    ),
                    {"id": uuid4(), "security_id": security_id, "now": now},
                )

        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO quotes "
                        "(id, security_id, as_of, price, currency, source, fetched_at, "
                        "quality_status, provider_metadata, created_at, updated_at) "
                        "VALUES (:id, :security_id, :now, -1, 'USD', 'invalid', :now, "
                        "'reported', '{}'::jsonb, :now, :now)"
                    ),
                    {"id": uuid4(), "security_id": security_id, "now": now},
                )
    engine.dispose()


def test_populated_0002_upgrade_reconciles_revisions_and_preserves_manual_history() -> (
    None
):
    """Upgrade realistic accepted data from the previous deployed schema."""
    database_url = environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL 16 database")

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from app.main import create_app

    engine = create_engine(database_url)
    _reset_schema(engine)
    _migrate(database_url, "0002_position_snapshot_revision")

    account_a, account_b, issuer_a, issuer_b, security_id = [uuid4() for _ in range(5)]
    snapshots_a = [uuid4() for _ in range(3)]
    snapshot_b = uuid4()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with engine.begin() as connection:
        for account_id, name, current_revision in (
            (account_a, "Upgrade taxable", 3),
            (account_b, "Upgrade IRA", 0),
        ):
            connection.execute(
                text(
                    "INSERT INTO accounts (id, name, account_type, base_currency, "
                    "active, current_position_revision, source_type, created_at, "
                    "updated_at) VALUES (:id, :name, 'taxable', 'USD', true, "
                    ":current_revision, 'manual', :now, :now)"
                ),
                {
                    "id": account_id,
                    "name": name,
                    "current_revision": current_revision,
                    "now": now,
                },
            )
        for issuer_id, name in (
            (issuer_a, "upgrade issuer a"),
            (issuer_b, "upgrade issuer b"),
        ):
            connection.execute(
                text(
                    "INSERT INTO issuers (id, normalized_name, display_name, "
                    "created_at, updated_at) "
                    "VALUES (:id, :normalized, :display, :now, :now)"
                ),
                {
                    "id": issuer_id,
                    "normalized": name,
                    "display": name.title(),
                    "now": now,
                },
            )
        # A shared alias value across issuers is intentionally retained as an
        # unresolved ambiguity rather than merged by a ticker/name shortcut.
        for issuer_id in (issuer_a, issuer_b):
            connection.execute(
                text(
                    "INSERT INTO issuer_aliases (id, issuer_id, alias, "
                    "normalized_alias, source) "
                    "VALUES (:id, :issuer_id, 'Shared Example', 'shared example', "
                    "'fixture')"
                ),
                {"id": uuid4(), "issuer_id": issuer_id},
            )
        connection.execute(
            text(
                "INSERT INTO securities (id, security_type, display_ticker, name, "
                "issuer_id, "
                "currency, created_at, updated_at) VALUES (:id, 'equity', 'UPG', "
                "'Upgrade Synthetic', :issuer_id, 'USD', :now, :now)"
            ),
            {"id": security_id, "issuer_id": issuer_a, "now": now},
        )

        snapshot_rows = [
            (
                snapshots_a[0],
                account_a,
                datetime(2026, 1, 5, tzinfo=UTC),
                "superseded",
                datetime(2026, 1, 6, tzinfo=UTC),
                1,
            ),
            (
                snapshots_a[1],
                account_a,
                datetime(2026, 2, 5, tzinfo=UTC),
                "accepted",
                datetime(2026, 2, 6, tzinfo=UTC),
                2,
            ),
            (
                snapshots_a[2],
                account_a,
                datetime(2026, 3, 5, tzinfo=UTC),
                "accepted",
                datetime(2026, 3, 6, tzinfo=UTC),
                3,
            ),
            (
                snapshot_b,
                account_b,
                datetime(2026, 4, 5, tzinfo=UTC),
                "accepted",
                datetime(2026, 4, 6, tzinfo=UTC),
                1,
            ),
        ]
        for (
            snapshot_id,
            account_id,
            snapshot_at,
            status,
            accepted_at,
            revision,
        ) in snapshot_rows:
            connection.execute(
                text(
                    "INSERT INTO position_snapshots (id, account_id, snapshot_at, "
                    "source, status, revision, accepted_at, created_at, updated_at) "
                    "VALUES (:id, :account_id, :snapshot_at, 'manual', :status, "
                    ":revision, "
                    ":accepted_at, :snapshot_at, :snapshot_at)"
                ),
                {
                    "id": snapshot_id,
                    "account_id": account_id,
                    "snapshot_at": snapshot_at,
                    "status": status,
                    "accepted_at": accepted_at,
                    "revision": revision,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO position_snapshot_lines (id, snapshot_id, "
                    "security_id, quantity, "
                    "reported_value, reported_price, currency, source, quality_status) "
                    "VALUES (:id, :snapshot_id, :security_id, :quantity, :value, "
                    "10, 'USD', "
                    "'manual', 'manual')"
                ),
                {
                    "id": uuid4(),
                    "snapshot_id": snapshot_id,
                    "security_id": security_id,
                    "quantity": Decimal("1.25"),
                    "value": Decimal("12.5"),
                },
            )

    _migrate(database_url)
    with engine.connect() as connection:
        accounts = connection.execute(
            text(
                "SELECT id, current_position_revision, current_position_snapshot_id "
                "FROM accounts ORDER BY id"
            )
        ).all()
        account_a_row = next(row for row in accounts if row.id == account_a)
        account_b_row = next(row for row in accounts if row.id == account_b)
        assert account_a_row.current_position_revision == 3
        assert account_a_row.current_position_snapshot_id == snapshots_a[2]
        assert account_b_row.current_position_revision == 1
        assert account_b_row.current_position_snapshot_id == snapshot_b

        revisions = connection.execute(
            text(
                "SELECT id, revision, status FROM position_snapshots "
                "WHERE account_id = :account_id AND source = 'manual' ORDER BY revision"
            ),
            {"account_id": account_a},
        ).all()
        assert [row.revision for row in revisions] == [1, 2, 3]
        assert revisions[0].status == "superseded"
        assert revisions[1].status == "superseded"
        assert revisions[2].status == "accepted"
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM position_snapshot_lines l "
                    "JOIN position_snapshots s ON s.id = l.snapshot_id "
                    "WHERE s.account_id = :account_id AND s.source = 'manual'"
                ),
                {"account_id": account_a},
            ).scalar_one()
            == 3
        )
        alias_state = connection.execute(
            text(
                "SELECT count(*) AS total, "
                "count(DISTINCT alias_namespace) AS namespaces, "
                "count(DISTINCT review_status) AS review_states FROM issuer_aliases "
                "WHERE normalized_alias = 'shared example'"
            )
        ).one()
        assert alias_state.total == 2
        assert alias_state.namespaces == alias_state.review_states == 1
        for exchange in ("NYSE", "NASDAQ"):
            connection.execute(
                text(
                    "INSERT INTO security_identifiers (id, security_id, "
                    "namespace, exchange, "
                    "value, normalized_value, valid_from, source, review_status) "
                    "VALUES (:id, :security_id, 'ticker', :exchange, 'UPG', 'upg', "
                    ":valid_from, 'fixture', 'reviewed')"
                ),
                {
                    "id": uuid4(),
                    "security_id": security_id,
                    "exchange": exchange,
                    "valid_from": date(2026, 1, 1),
                },
            )
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO security_identifiers (id, security_id, "
                        "namespace, exchange, "
                        "value, normalized_value, valid_from, source, review_status) "
                        "VALUES (:id, :security_id, 'ticker', 'NYSE', 'UPG', 'upg', "
                        ":valid_from, 'fixture', 'reviewed')"
                    ),
                    {
                        "id": uuid4(),
                        "security_id": security_id,
                        "valid_from": date(2026, 1, 1),
                    },
                )

    app = create_app(engine=engine)
    with TestClient(app, raise_server_exceptions=False) as client:
        path = f"/v1/accounts/{account_a}/positions"
        saved = client.put(
            path,
            json={
                "expected_revision": 3,
                "effective_date": "2026-03-05",
                "positions": [
                    {
                        "security_id": str(security_id),
                        "quantity": "5",
                        "reported_price": "20",
                        "currency": "USD",
                    }
                ],
            },
        )
        assert saved.status_code == 200
        assert saved.json()["revision"] == 4
        latest_id = UUID(saved.json()["id"])

        factory = app.state.session_factory
        failed_once = False

        def fail_commit_once(session: object) -> None:
            nonlocal failed_once
            if not failed_once:
                failed_once = True
                raise RuntimeError("synthetic commit interruption")

        event.listen(factory, "before_commit", fail_commit_once)
        failed = client.put(
            path,
            json={
                "expected_revision": 4,
                "effective_date": "2026-03-05",
                "positions": [
                    {
                        "security_id": str(security_id),
                        "quantity": "7",
                        "reported_price": "20",
                        "currency": "USD",
                    }
                ],
            },
        )
        event.remove(factory, "before_commit", fail_commit_once)
        assert failed.status_code == 500

        with factory() as session:
            account = session.execute(
                text(
                    "SELECT current_position_revision, current_position_snapshot_id "
                    "FROM accounts WHERE id = :id"
                ),
                {"id": account_a},
            ).one()
            assert account.current_position_revision == 4
            assert account.current_position_snapshot_id == latest_id
            assert (
                session.execute(
                    text(
                        "SELECT count(*) FROM position_snapshots "
                        "WHERE account_id = :id AND source = 'manual'"
                    ),
                    {"id": account_a},
                ).scalar_one()
                == 4
            )
            assert (
                session.execute(
                    text(
                        "SELECT count(*) FROM position_snapshot_lines "
                        "WHERE snapshot_id = :id"
                    ),
                    {"id": snapshots_a[2]},
                ).scalar_one()
                == 1
            )
    engine.dispose()
