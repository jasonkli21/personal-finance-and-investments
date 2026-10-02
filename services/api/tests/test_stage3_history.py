"""Synthetic API checks for source-backed history and return boundaries."""

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Security
from app.main import create_app


@pytest.fixture
def stage3_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, UUID]]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    security_id = uuid4()
    with Session(engine) as session:
        session.add(
            Security(
                id=security_id,
                security_type="equity",
                display_ticker="ACME",
                name="Synthetic Acme",
                currency="USD",
            )
        )
        session.commit()
    with TestClient(create_app(engine=engine)) as client:
        yield client, security_id
    engine.dispose()


def _account(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/v1/accounts",
        json={
            "name": "Synthetic taxable",
            "account_type": "taxable",
            "base_currency": "USD",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _replace_position(
    client: TestClient,
    account_id: str,
    security_id: UUID,
    *,
    revision: int,
    date_text: str,
    quantity: str,
) -> None:
    response = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": revision,
            "effective_date": date_text,
            "positions": [
                {
                    "security_id": str(security_id),
                    "quantity": quantity,
                    "reported_price": "100",
                    "currency": "USD",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text


def test_external_deposit_does_not_turn_flat_market_into_return(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = stage3_client
    account = _account(client)
    account_id = account["id"]
    _replace_position(
        client,
        account_id,
        security_id,
        revision=0,
        date_text="2026-01-01",
        quantity="10",
    )
    event = {
        "account_id": account_id,
        "event_type": "deposit",
        "effective_date": "2026-01-16",
        "cash_amount": "500",
        "currency": "USD",
        "source_label": "synthetic test",
        "idempotency_key": "stage3-deposit-001",
    }
    first = client.post("/v1/portfolio/history/events", json=event)
    second = client.post("/v1/portfolio/history/events", json=event)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["is_external_flow"] is True
    history_response = client.get(
        "/v1/portfolio/history",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    )
    assert history_response.status_code == 200, history_response.text
    assert len(history_response.json()["events"]) == 1
    assert len(history_response.json()["snapshots"]) == 1

    _replace_position(
        client,
        account_id,
        security_id,
        revision=1,
        date_text="2026-02-01",
        quantity="15",
    )
    response = client.get(
        "/v1/portfolio/performance",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "available"
    assert result["time_weighted_return"] == "0.000000000000"
    assert result["money_weighted_return"] == "0.000000000000"
    assert result["external_flow_count"] == 1


def test_history_reconciliation_reports_discrepancy_without_inventing_event(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = stage3_client
    account = _account(client)
    account_id = account["id"]
    _replace_position(
        client,
        account_id,
        security_id,
        revision=0,
        date_text="2026-01-01",
        quantity="10",
    )
    _replace_position(
        client,
        account_id,
        security_id,
        revision=1,
        date_text="2026-02-01",
        quantity="12",
    )
    response = client.get(
        "/v1/portfolio/history/reconcile",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "discrepancy"
    assert result["differences"][0]["difference"] == "2.0000000000"
    assert result["gaps"] == []
