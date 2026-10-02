"""Synthetic golden and boundary checks for read-only sale scenarios."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Account,
    Base,
    InvestmentEvent,
    PositionSnapshot,
    PositionSnapshotLine,
    Security,
    TaxLot,
)
from app.main import create_app


@pytest.fixture
def sales_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, UUID]]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    security_id = UUID("10000000-0000-4000-8000-000000000001")
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


def _account(client: TestClient, name: str = "Synthetic taxable") -> str:
    response = client.post(
        "/v1/accounts",
        json={"name": name, "account_type": "taxable", "base_currency": "USD"},
    )
    assert response.status_code == 201, response.text
    return cast(str, cast(dict[str, Any], response.json())["id"])


def _accept_position(
    client: TestClient,
    account_id: str,
    security_id: UUID,
    quantity: str,
    *,
    effective_date: date | None = None,
) -> None:
    response = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": (effective_date or date.today()).isoformat(),
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


def _publish_lots(
    client: TestClient,
    account_id: str,
    *,
    source_rows: bytes,
    key: str,
) -> list[dict[str, Any]]:
    staged = client.post(
        "/v1/imports/tax-lots/preview",
        content=source_rows,
        headers={
            "Content-Type": "text/csv",
            "X-Account-Id": account_id,
            "X-Source-Label": "Synthetic broker export",
            "X-Column-Mapping": (
                '{"ticker":"Symbol","source_lot_id":"Lot ID",'
                '"acquired_at":"Acquired","initial_quantity":"Original Shares",'
                '"remaining_quantity":"Shares","remaining_basis":"Basis",'
                '"basis_currency":"Currency"}'
            ),
            "X-File-Name": "synthetic-lots.csv",
            "Idempotency-Key": key,
        },
    )
    assert staged.status_code == 201, staged.text
    review = client.get(f"/v1/tax-lot-imports/{staged.json()['id']}")
    assert review.status_code == 200, review.text
    publication = client.post(
        f"/v1/tax-lot-imports/{staged.json()['id']}/publish",
        json={
            "expected_revision": review.json()["review_revision"],
            "acknowledge_quantity_differences": True,
            "reason": "Synthetic test data publication",
        },
    )
    assert publication.status_code == 200, publication.text
    lots = client.get("/v1/tax-lots", params={"account_id": account_id})
    assert lots.status_code == 200, lots.text
    return cast(list[dict[str, Any]], lots.json())


def _snapshot_state(client: TestClient) -> tuple[int, int, int, int]:
    factory = cast(Any, client.app).state.session_factory
    with factory() as session:
        return (
            session.scalar(select(func.count()).select_from(PositionSnapshot)) or 0,
            session.scalar(select(func.count()).select_from(TaxLot)) or 0,
            session.scalar(select(func.count()).select_from(InvestmentEvent)) or 0,
            sum(
                account.current_position_revision
                for account in session.scalars(select(Account))
            ),
        )


def test_golden_two_lot_comparison_is_read_only(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    _accept_position(client, account_id, security_id, "20")
    lots = _publish_lots(
        client,
        account_id,
        source_rows=(
            b"Symbol,Lot ID,Acquired,Original Shares,Shares,Basis,Currency\n"
            b"ACME,LOW,2020-02-03,10,10,500,USD\n"
            b"ACME,HIGH,2021-04-05,10,10,800,USD\n"
        ),
        key="sale-golden-lots",
    )
    before = _snapshot_state(client)
    request = {
        "account_id": account_id,
        "security_id": str(security_id),
        "sale_date": date.today().isoformat(),
        "target_type": "shares",
        "target_amount": "10",
        "scenarios": [
            {
                "label": "Lower basis",
                "fee_amount": "0",
                "selections": [{"lot_id": lots[0]["id"], "quantity": "10"}],
            },
            {
                "label": "Higher basis",
                "fee_amount": "0",
                "selections": [{"lot_id": lots[1]["id"], "quantity": "10"}],
            },
        ],
    }
    response = client.post("/v1/simulations/sales", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["methodology_version"] == "hypothetical-lot-sale-v1"
    assert result["baseline"]["price"] == "100.0000000000"
    assert result["scenarios"][0]["estimated_gain_loss"] == "500.0000000000"
    assert result["scenarios"][1]["estimated_gain_loss"] == "200.0000000000"
    assert result["scenarios"][0]["lots"][0]["holding_period_candidate"] == "long_term"
    assert result["canonical_records_mutated"] is False
    assert result["persisted"] is False
    assert result["scenarios"][0]["potential_wash_sale"]["coverage"] == "unknown"
    assert _snapshot_state(client) == before


def test_partial_lot_fees_and_value_rounding_reconcile(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    _accept_position(client, account_id, security_id, "10")
    lots = _publish_lots(
        client,
        account_id,
        source_rows=(
            b"Symbol,Lot ID,Acquired,Original Shares,Shares,Basis,Currency\n"
            b"ACME,PARTIAL,2022-05-01,10,10,500,USD\n"
        ),
        key="sale-partial-lot",
    )
    response = client.post(
        "/v1/simulations/sales",
        json={
            "account_id": account_id,
            "security_id": str(security_id),
            "sale_date": date.today().isoformat(),
            "target_type": "value",
            "target_amount": "400.000000009",
            "scenarios": [
                {
                    "label": "Partial with fee",
                    "fee_amount": "1",
                    "selections": [{"lot_id": lots[0]["id"], "quantity": "4"}],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    scenario = response.json()["scenarios"][0]
    assert scenario["target_shares"] == "4.0000000000"
    assert scenario["gross_proceeds"] == "400.0000000000"
    assert scenario["value_rounding_remainder"] == "0.0000000090"
    assert scenario["selected_basis"] == "200.0000000000"
    assert scenario["fees"] == "1"
    assert scenario["estimated_gain_loss"] == "199.0000000000"
    assert scenario["lots"][0]["remaining_quantity"] == "6.0000000000"
    assert scenario["lots"][0]["remaining_basis"] == "300.0000000000"


def test_missing_basis_remains_unavailable(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    _accept_position(client, account_id, security_id, "10")
    lots = _publish_lots(
        client,
        account_id,
        source_rows=(
            b"Symbol,Lot ID,Acquired,Original Shares,Shares,Basis,Currency\n"
            b"ACME,UNKNOWN,2024-01-01,10,10,,\n"
        ),
        key="sale-missing-basis",
    )
    response = client.post(
        "/v1/simulations/sales",
        json={
            "account_id": account_id,
            "security_id": str(security_id),
            "sale_date": date.today().isoformat(),
            "target_type": "shares",
            "target_amount": "2",
            "scenarios": [
                {
                    "label": "Unknown basis",
                    "selections": [{"lot_id": lots[0]["id"], "quantity": "2"}],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    scenario = response.json()["scenarios"][0]
    assert scenario["basis_status"] == "unavailable"
    assert scenario["estimated_gain_loss"] is None
    assert scenario["potential_wash_sale"]["status"] == "unknown"


def test_stale_accepted_price_is_rejected(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    _accept_position(client, account_id, security_id, "10")
    factory = cast(Any, client.app).state.session_factory
    with factory() as session:
        account = session.scalar(select(Account).where(Account.id == UUID(account_id)))
        assert account is not None
        line = session.scalar(
            select(PositionSnapshotLine).where(
                PositionSnapshotLine.snapshot_id == account.current_position_snapshot_id
            )
        )
        assert line is not None
        line.quality_status = "stale"
        session.commit()
    response = client.post(
        "/v1/simulations/sales",
        json={
            "account_id": account_id,
            "security_id": str(security_id),
            "sale_date": date.today().isoformat(),
            "target_type": "shares",
            "target_amount": "1",
            "scenarios": [
                {
                    "label": "Stale price",
                    "selections": [
                        {
                            "lot_id": "20000000-0000-4000-8000-000000000001",
                            "quantity": "1",
                        }
                    ],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "stale" in response.json()["detail"]


def test_old_position_snapshot_is_rejected(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    _accept_position(
        client,
        account_id,
        security_id,
        "10",
        effective_date=date.today() - timedelta(days=8),
    )
    response = client.post(
        "/v1/simulations/sales",
        json={
            "account_id": account_id,
            "security_id": str(security_id),
            "sale_date": date.today().isoformat(),
            "target_type": "shares",
            "target_amount": "1",
            "scenarios": [
                {
                    "label": "Stale snapshot",
                    "selections": [
                        {
                            "lot_id": "20000000-0000-4000-8000-000000000001",
                            "quantity": "1",
                        }
                    ],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert "snapshot is more than 7 days old" in response.json()["detail"]


def test_cross_account_purchase_triggers_only_a_potential_warning(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    other_account_id = _account(client, "Other tracked account")
    _accept_position(client, account_id, security_id, "10")
    lots = _publish_lots(
        client,
        account_id,
        source_rows=(
            b"Symbol,Lot ID,Acquired,Original Shares,Shares,Basis,Currency\n"
            b"ACME,LOSS,2024-01-01,10,10,1200,USD\n"
        ),
        key="sale-loss-warning",
    )
    today = date.today()
    purchase = client.post(
        "/v1/portfolio/history/events",
        json={
            "account_id": other_account_id,
            "security_id": str(security_id),
            "event_type": "buy",
            "effective_date": (today - timedelta(days=5)).isoformat(),
            "quantity_delta": "1",
            "cash_amount": "-100",
            "currency": "USD",
            "source_label": "Synthetic second account purchase",
            "quality_status": "reported",
            "idempotency_key": "sale-warning-purchase",
        },
    )
    assert purchase.status_code == 201, purchase.text
    response = client.post(
        "/v1/simulations/sales",
        json={
            "account_id": account_id,
            "security_id": str(security_id),
            "sale_date": today.isoformat(),
            "target_type": "shares",
            "target_amount": "1",
            "scenarios": [
                {
                    "label": "Loss sale",
                    "selections": [{"lot_id": lots[0]["id"], "quantity": "1"}],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    warning = response.json()["scenarios"][0]["potential_wash_sale"]
    assert warning["status"] == "potential_match"
    assert warning["coverage"] == "unknown"
    assert any(
        match["source_type"] == "investment_event"
        and match["account_id"] == other_account_id
        for match in warning["matches"]
    )
    assert "not tax-compliance clearance" in warning["disclosure"]


def test_invalid_over_sale_and_changed_baseline_are_recoverable(
    sales_client: tuple[TestClient, UUID],
) -> None:
    client, security_id = sales_client
    account_id = _account(client)
    _accept_position(client, account_id, security_id, "10")
    lots = _publish_lots(
        client,
        account_id,
        source_rows=(
            b"Symbol,Lot ID,Acquired,Original Shares,Shares,Basis,Currency\n"
            b"ACME,ONLY,2020-01-01,10,10,500,USD\n"
        ),
        key="sale-overage",
    )
    request = {
        "account_id": account_id,
        "security_id": str(security_id),
        "sale_date": date.today().isoformat(),
        "target_type": "shares",
        "target_amount": "11",
        "scenarios": [
            {
                "label": "Too many",
                "selections": [{"lot_id": lots[0]["id"], "quantity": "11"}],
            }
        ],
    }
    over_sale = client.post("/v1/simulations/sales", json=request)
    assert over_sale.status_code == 422

    revised = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 1,
            "effective_date": date.today().isoformat(),
            "positions": [
                {
                    "security_id": str(security_id),
                    "quantity": "9",
                    "reported_price": "100",
                    "currency": "USD",
                }
            ],
        },
    )
    assert revised.status_code == 200, revised.text
    valid_target_old_scenario = {
        **request,
        "target_amount": "1",
        "scenarios": [
            {
                "label": "Old evidence selection",
                "selections": [{"lot_id": lots[0]["id"], "quantity": "1"}],
            }
        ],
    }
    changed = client.post("/v1/simulations/sales", json=valid_target_old_scenario)
    assert changed.status_code == 200, changed.text
    assert changed.json()["baseline"]["account_position_revision"] == 2
    assert changed.json()["baseline"]["position_quantity"] == "9.0000000000"
