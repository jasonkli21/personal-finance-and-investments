"""Run synthetic advanced workflows against migrated PostgreSQL, never real data.

TEST_DATABASE_URL must name an exclusive disposable PostgreSQL 16 database.
The API cases are shared with the offline suite so this gate exercises the same
public behavior using actual NUMERIC, JSONB, foreign keys, and transactions.
"""

from collections.abc import Callable, Iterator
from decimal import localcontext
from os import environ
from pathlib import Path
from typing import Never
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from test_core_schema import _migrate, _reset_schema
from test_stage3_history import (
    test_external_deposit_does_not_turn_flat_market_into_return as verify_history,
)
from test_stage3_planning import (
    test_monthly_projection_uses_explicit_inputs_and_scheduled_purchase as plan,
)
from test_stage3_sales import (
    test_golden_two_lot_comparison_is_read_only as verify_sales,
)
from test_stage3_tax_lots import (
    test_review_publish_is_idempotent_and_preserves_individual_lots as verify_tax_lots,
)
from test_stage5_research import (
    _add_documents,
    _fixture,
    _issuer,
)
from test_stage5_research import (
    test_portfolio_context_notes_and_watchlist_are_frozen_locally as verify_research,
)

from app.db.models import Security
from app.db.transactions import run_database_unit
from app.main import create_app


@pytest.fixture
def postgres_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, UUID, UUID]]:
    database_url = environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL 16 database")
    # CI usually returns UTC timestamps; use a non-UTC session to pin the date
    # normalization invariant regardless of the cluster's own TimeZone setting.
    engine = create_engine(
        database_url, connect_args={"options": "-c timezone=America/Los_Angeles"}
    )
    equity_id, cash_id = uuid4(), uuid4()
    try:
        _reset_schema(engine)
        _migrate(database_url)
        monkeypatch.setenv("DATABASE_BACKEND", "postgres")
        monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))

        def reveal_synthetic_failure(request: Request, error: SQLAlchemyError) -> Never:
            raise error

        # These fixtures contain only synthetic data. Preserve the driver's
        # failure in this gate instead of hiding a persistence defect behind 503.
        monkeypatch.setattr("app.main._database_unavailable", reveal_synthetic_failure)

        def reveal_research_conflict[T](
            factory: sessionmaker[Session], operation: Callable[[Session], T]
        ) -> T:
            try:
                return run_database_unit(factory, operation)
            except IntegrityError as exc:
                raise RuntimeError("Synthetic research integrity failure") from exc

        monkeypatch.setattr(
            "app.api.research_routes.run_database_unit", reveal_research_conflict
        )
        with Session(engine) as session:
            session.add_all(
                [
                    Security(
                        id=equity_id,
                        security_type="equity",
                        display_ticker="ACME",
                        name="Synthetic Acme",
                        currency="USD",
                    ),
                    Security(
                        id=cash_id,
                        security_type="cash",
                        display_ticker="CASH",
                        name="Synthetic Cash",
                        currency="USD",
                    ),
                ]
            )
            session.commit()
        with TestClient(create_app(engine=engine)) as client:
            yield client, equity_id, cash_id
    finally:
        engine.dispose()


def test_postgres_history_neutralizes_deposits(
    postgres_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, equity_id, _cash_id = postgres_client
    verify_history((client, equity_id))


def test_postgres_tax_lot_publication_and_adjustment_are_idempotent(
    postgres_client: tuple[TestClient, UUID, UUID],
) -> None:
    verify_tax_lots(postgres_client)


def test_postgres_lot_sale_preserves_canonical_records(
    postgres_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, equity_id, _cash_id = postgres_client
    verify_sales((client, equity_id))


def test_postgres_planning_preserves_canonical_records(
    postgres_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, _equity_id, _cash_id = postgres_client
    plan(client)


def test_postgres_research_preserves_frozen_report_and_note_lineage(
    postgres_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, _equity_id, _cash_id = postgres_client
    verify_research(client)


def test_postgres_fact_idempotency_preserves_last_supported_digit(
    postgres_client: tuple[TestClient, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _equity_id, _cash_id = postgres_client
    issuer_id = _issuer(client)
    document = _add_documents(client, issuer_id)[0]

    def reduced_precision_unit[T](
        factory: sessionmaker[Session], operation: Callable[[Session], T]
    ) -> T:
        with localcontext() as context:
            context.prec = 8
            return run_database_unit(factory, operation)

    # The request runs in a worker thread, so set the context at the domain
    # operation boundary rather than only in pytest's thread.
    monkeypatch.setattr(
        "app.api.research_routes.run_database_unit", reduced_precision_unit
    )
    value = "123456789012345678.1234567891"
    payload = {
        **_fixture()["facts"][0],
        "document_id": document["id"],
        "normalized_value": value,
    }
    first = client.post("/v1/research/facts", json=payload)
    again = client.post("/v1/research/facts", json=payload)
    changed = client.post(
        "/v1/research/facts",
        json={**payload, "normalized_value": "123456789012345678.1234567892"},
    )
    assert first.status_code == again.status_code == 201, first.text
    assert first.json()["normalized_value"] == value
    assert again.json()["normalized_value"] == value
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["duplicate"] is True
    assert changed.status_code == 409, changed.text
