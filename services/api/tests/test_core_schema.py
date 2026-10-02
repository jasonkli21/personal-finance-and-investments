"""Core schema integration coverage; set TEST_DATABASE_URL to a disposable PG16 DB."""

import subprocess
import sys
from datetime import UTC, datetime
from decimal import Decimal
from os import environ
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


def test_core_schema_migration_and_round_trip() -> None:
    database_url = environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL 16 database")

    api_dir = Path(__file__).parents[1]
    migration_env = environ.copy()
    migration_env["DATABASE_URL"] = database_url
    migration_env["DATABASE_BACKEND"] = "postgres"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_dir,
        env=migration_env,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = create_engine(database_url)
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

        # Source-scoped snapshot identity prevents the same import being duplicated.
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
