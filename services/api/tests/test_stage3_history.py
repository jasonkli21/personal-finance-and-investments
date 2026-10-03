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


def _cash_security(client: TestClient) -> str:
    response = client.post(
        "/v1/securities",
        json={
            "security_type": "cash",
            "display_ticker": "USD",
            "name": "Synthetic USD cash",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])


def _replace_cash_position(
    client: TestClient,
    account_id: str,
    cash_id: str,
    *,
    revision: int,
    date_text: str,
    amount: str,
) -> None:
    response = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": revision,
            "effective_date": date_text,
            "positions": [
                {"security_id": cash_id, "quantity": amount, "currency": "USD"}
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


def test_account_transfer_is_neutralized_but_not_counted_as_external_flow(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, _security_id = stage3_client
    account_id = _account(client)["id"]
    cash_id = _cash_security(client)
    _replace_cash_position(
        client, account_id, cash_id, revision=0, date_text="2026-01-01", amount="1000"
    )
    event = client.post(
        "/v1/portfolio/history/events",
        json={
            "account_id": account_id,
            "security_id": cash_id,
            "event_type": "transfer_in",
            "effective_date": "2026-01-16",
            "quantity_delta": "500",
            "cash_amount": "500",
            "currency": "USD",
            "source_label": "Synthetic transfer",
            "idempotency_key": "transfer-flat-001",
        },
    )
    assert event.status_code == 201, event.text
    _replace_cash_position(
        client, account_id, cash_id, revision=1, date_text="2026-02-01", amount="1500"
    )
    result = client.get(
        "/v1/portfolio/performance",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    ).json()
    assert result["status"] == "available"
    assert result["time_weighted_return"] == "0.000000000000"
    assert result["money_weighted_return"] == "0.000000000000"
    assert result["external_flow_count"] == 0


def test_missing_transfer_value_and_unsupported_event_withhold_performance(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = stage3_client
    account_id = _account(client)["id"]
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
        quantity="10",
    )
    for event_type, key, payload in (
        ("transfer_in", "missing-transfer-value", {"quantity_delta": "1"}),
        ("other", "unsupported-event", {}),
    ):
        response = client.post(
            "/v1/portfolio/history/events",
            json={
                "account_id": account_id,
                "security_id": str(security_id)
                if event_type == "transfer_in"
                else None,
                "event_type": event_type,
                "effective_date": "2026-01-16",
                "currency": "USD",
                "source_label": "Synthetic review",
                "idempotency_key": key,
                **payload,
            },
        )
        assert response.status_code == 201, response.text
    result = client.get(
        "/v1/portfolio/performance",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    ).json()
    assert result["status"] == "unavailable"
    assert result["time_weighted_return"] is None


def test_event_replay_with_changed_quality_status_conflicts(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = stage3_client
    account_id = _account(client)["id"]
    event = {
        "account_id": account_id,
        "security_id": str(security_id),
        "event_type": "buy",
        "effective_date": "2026-01-15",
        "quantity_delta": "1",
        "currency": "USD",
        "source_label": "Synthetic trade",
        "quality_status": "estimated",
        "idempotency_key": "same-key-different-quality",
    }
    assert client.post("/v1/portfolio/history/events", json=event).status_code == 201
    replay = client.post(
        "/v1/portfolio/history/events",
        json={**event, "quality_status": "reported"},
    )
    assert replay.status_code == 409


def test_cash_reconciliation_applies_reviewed_buy_and_fee_but_skips_unreviewed_buy(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, equity_id = stage3_client
    account_id = _account(client)["id"]
    cash_id = _cash_security(client)
    initial = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": "2026-01-01",
            "positions": [
                {
                    "security_id": str(equity_id),
                    "quantity": "10",
                    "reported_price": "100",
                    "currency": "USD",
                },
                {"security_id": cash_id, "quantity": "1000", "currency": "USD"},
            ],
        },
    )
    assert initial.status_code == 200, initial.text
    for event_type, quantity, amount, key, quality in (
        ("buy", "1", "-100", "reviewed-buy", "reported"),
        ("fee", None, "-5", "reviewed-fee", "reported"),
        ("buy", "1", "-100", "unreviewed-buy", "estimated"),
    ):
        response = client.post(
            "/v1/portfolio/history/events",
            json={
                "account_id": account_id,
                "security_id": str(equity_id) if event_type == "buy" else None,
                "event_type": event_type,
                "effective_date": "2026-01-16",
                "quantity_delta": quantity,
                "cash_amount": amount,
                "currency": "USD",
                "source_label": "Synthetic statement",
                "idempotency_key": key,
                "quality_status": quality,
            },
        )
        assert response.status_code == 201, response.text
    ending = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 1,
            "effective_date": "2026-02-01",
            "positions": [
                {
                    "security_id": str(equity_id),
                    "quantity": "11",
                    "reported_price": "100",
                    "currency": "USD",
                },
                {"security_id": cash_id, "quantity": "895", "currency": "USD"},
            ],
        },
    )
    assert ending.status_code == 200, ending.text
    result = client.get(
        "/v1/portfolio/history/reconcile",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    ).json()
    assert result["status"] == "discrepancy"
    differences = {
        row["security_id"]: row["difference"] for row in result["differences"]
    }
    assert "0E-10" in differences.values()
    assert all(value == "0E-10" for value in differences.values())
    assert any("has not been reviewed" in gap for gap in result["gaps"])


def test_buy_without_unambiguous_cash_security_is_a_reconciliation_gap(
    stage3_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = stage3_client
    account_id = _account(client)["id"]
    _replace_position(
        client,
        account_id,
        security_id,
        revision=0,
        date_text="2026-01-01",
        quantity="10",
    )
    event = client.post(
        "/v1/portfolio/history/events",
        json={
            "account_id": account_id,
            "security_id": str(security_id),
            "event_type": "buy",
            "effective_date": "2026-01-16",
            "quantity_delta": "1",
            "cash_amount": "-100",
            "currency": "USD",
            "source_label": "Synthetic transaction",
            "idempotency_key": "buy-without-cash-line",
        },
    )
    assert event.status_code == 201, event.text
    _replace_position(
        client,
        account_id,
        security_id,
        revision=1,
        date_text="2026-02-01",
        quantity="11",
    )
    result = client.get(
        "/v1/portfolio/history/reconcile",
        params={
            "account_id": account_id,
            "start_date": "2026-01-01",
            "end_date": "2026-02-01",
        },
    ).json()
    assert result["status"] == "discrepancy"
    assert any("cannot be matched" in gap for gap in result["gaps"])
