"""Synthetic hypothetical portfolio allocation and exposure scenarios."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.db.models import Account, Base, FundSnapshot, PositionSnapshot
from app.main import create_app


@pytest.fixture
def scenario_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with TestClient(create_app(engine=engine)) as client:
        yield client
    engine.dispose()


def _account(client: TestClient, name: str = "Synthetic brokerage") -> str:
    response = client.post(
        "/v1/accounts",
        json={"name": name, "account_type": "taxable", "base_currency": "USD"},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])


def _security(client: TestClient, ticker: str, security_type: str = "equity") -> str:
    response = client.post(
        "/v1/securities",
        json={
            "security_type": security_type,
            "display_ticker": ticker,
            "name": f"Synthetic {ticker}",
            "currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])


def _positions(
    client: TestClient,
    account_id: str,
    items: list[tuple[str, str, str | None]],
) -> str:
    positions = []
    for security_id, quantity, price in items:
        position: dict[str, Any] = {
            "security_id": security_id,
            "quantity": quantity,
            "currency": "USD",
        }
        if price is not None:
            position["reported_price"] = price
        positions.append(position)
    response = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": date.today().isoformat(),
            "positions": positions,
        },
    )
    assert response.status_code == 200, response.text
    return cast(str, response.json()["id"])


def _publish_fund(client: TestClient, fund_id: str, rows: bytes) -> str:
    uploaded = client.post(
        f"/v1/funds/{fund_id}/upload",
        content=rows,
        headers={
            "X-Effective-Date": date.today().isoformat(),
            "X-Column-Mapping": (
                '{"identifier":"ticker","weight":"weight","asset_type":"type"}'
            ),
            "X-Weight-Unit": "percent",
            "Idempotency-Key": f"scenario-fund-{fund_id}",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    published = client.post(
        f"/v1/fund-imports/{uploaded.json()['id']}/publish",
        json={"expected_review_revision": 1},
    )
    assert published.status_code == 200, published.text
    return cast(str, published.json()["id"])


def _payload(
    account_id: str, *, trades: list[dict[str, Any]], **extra: Any
) -> dict[str, Any]:
    return {
        "account_ids": [account_id],
        "as_of": datetime.now(UTC).isoformat(),
        "financing_policy": "cash_only",
        "trades": trades,
        **extra,
    }


def _record_counts(client: TestClient) -> tuple[int, int, int]:
    factory = cast(Any, client.app).state.session_factory
    with factory() as session:
        return (
            session.scalar(select(func.count()).select_from(PositionSnapshot)) or 0,
            session.scalar(select(func.count()).select_from(FundSnapshot)) or 0,
            sum(
                account.current_position_revision
                for account in session.scalars(select(Account))
            ),
        )


def test_equity_buy_reconciles_fee_cash_and_category_targets(
    scenario_client: TestClient,
) -> None:
    client = scenario_client
    account_id = _account(client)
    equity_id = _security(client, "ACME")
    cash_id = _security(client, "CASH", "cash")
    snapshot_id = _positions(
        client,
        account_id,
        [(equity_id, "10", "100"), (cash_id, "1000", None)],
    )
    before_records = _record_counts(client)
    response = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": equity_id,
                    "side": "buy",
                    "quantity": "2",
                    "price": "100",
                    "fee_amount": "5",
                    "currency": "USD",
                }
            ],
            category_targets=[
                {"category": "direct", "target_percent": "60"},
                {"category": "cash", "target_percent": "40"},
            ],
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["canonical_records_mutated"] is False
    assert result["persisted"] is False
    assert result["position_snapshot_ids"][account_id] == snapshot_id
    assert Decimal(result["before"]["included_valued_nav"]) == 2000
    assert Decimal(result["after"]["included_valued_nav"]) == 1995
    assert Decimal(result["after"]["direct_assets"]) == 1200
    assert Decimal(result["after"]["residual"]) == 795
    assert Decimal(result["after"]["direct_assets"]) + Decimal(
        result["after"]["indirect_lookthrough"]
    ) + Decimal(result["after"]["residual"]) == Decimal(
        result["after"]["included_valued_nav"]
    )
    drift = {row["category"]: row for row in result["after"]["drift_rows"]}
    assert drift["direct"]["drift_percentage_points"] is not None
    assert result["cash"][0]["cash_after"] == "795.0000000000"
    assert _record_counts(client) == before_records


def test_cash_only_policy_rejects_insufficient_cash_and_short_sale(
    scenario_client: TestClient,
) -> None:
    client = scenario_client
    account_id = _account(client)
    equity_id = _security(client, "ACME")
    cash_id = _security(client, "CASH", "cash")
    _positions(
        client,
        account_id,
        [(equity_id, "2", "100"), (cash_id, "500", None)],
    )
    too_large = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": equity_id,
                    "side": "buy",
                    "quantity": "6",
                    "price": "100",
                    "fee_amount": "1",
                    "currency": "USD",
                }
            ],
        ),
    )
    assert too_large.status_code == 422
    assert "available cash" in too_large.json()["detail"]
    oversold = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": equity_id,
                    "side": "sell",
                    "quantity": "3",
                    "price": "100",
                    "currency": "USD",
                }
            ],
        ),
    )
    assert oversold.status_code == 422
    assert "exceeds the actual owned position" in oversold.json()["detail"]


def test_new_etf_buy_uses_dated_lookthrough_and_preserves_unknown_cash(
    scenario_client: TestClient,
) -> None:
    client = scenario_client
    account_id = _account(client)
    cash_id = _security(client, "CASH", "cash")
    fund_id = _security(client, "FUND", "etf")
    _security(client, "ACME")
    _security(client, "OTHER")
    _positions(client, account_id, [(cash_id, "1000", None)])
    _publish_fund(
        client,
        fund_id,
        b"ticker,weight,type\nACME,60,equity\nOTHER,40,equity\n",
    )
    response = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": fund_id,
                    "side": "buy",
                    "quantity": "5",
                    "price": "100",
                    "fee_amount": "0",
                    "currency": "USD",
                }
            ],
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["before"]["indirect_lookthrough"] == "0"
    assert Decimal(result["after"]["indirect_lookthrough"]) == 500
    assert Decimal(result["after"]["residual"]) == 500
    assert result["after"]["fund_snapshots"][0]["security_id"] == fund_id
    assert result["after"]["fund_snapshots"][0]["as_of"] == date.today().isoformat()


def test_opaque_fund_and_foreign_cash_remain_visible_and_nav_is_incomplete(
    scenario_client: TestClient,
) -> None:
    client = scenario_client
    account_id = _account(client)
    usd_cash_id = _security(client, "CASH", "cash")
    eur_cash_response = client.post(
        "/v1/securities",
        json={
            "security_type": "cash",
            "display_ticker": "EUR-CASH",
            "name": "Synthetic EUR cash",
            "currency": "EUR",
        },
    )
    assert eur_cash_response.status_code == 201, eur_cash_response.text
    eur_cash_id = eur_cash_response.json()["id"]
    fund_id = _security(client, "OPAQUE", "etf")
    snapshot = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": date.today().isoformat(),
            "positions": [
                {"security_id": usd_cash_id, "quantity": "600", "currency": "USD"},
                {"security_id": eur_cash_id, "quantity": "200", "currency": "EUR"},
            ],
        },
    )
    assert snapshot.status_code == 200, snapshot.text

    response = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": fund_id,
                    "side": "buy",
                    "quantity": "1",
                    "price": "100",
                    "currency": "USD",
                }
            ],
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["after"]["nav_status"] == "incomplete"
    assert result["after"]["percentages_available"] is False
    assert Decimal(result["after"]["included_valued_nav"]) == 600
    assert Decimal(result["after"]["opaque_and_unknown_value"]) == 100
    assert result["cash"][0]["cash_after"] == "500.0000000000"
    assert any(
        "missing or unsupported composition" in item
        for item in result["after"]["warnings"]
    )
    assert any("EUR value is excluded" in item for item in result["after"]["warnings"])


def test_etf_sale_removes_lookthrough_and_shared_membership_without_double_count(
    scenario_client: TestClient,
) -> None:
    client = scenario_client
    account_id = _account(client)
    fund_a = _security(client, "FA", "etf")
    fund_b = _security(client, "FB", "etf")
    cash_id = _security(client, "CASH", "cash")
    _security(client, "ACME")
    _security(client, "OTHER")
    snapshot_id = _positions(
        client,
        account_id,
        [(fund_a, "10", "100"), (fund_b, "5", "100"), (cash_id, "1000", None)],
    )
    _publish_fund(
        client, fund_a, b"ticker,weight,type\nACME,50,equity\nOTHER,50,equity\n"
    )
    _publish_fund(
        client, fund_b, b"ticker,weight,type\nACME,40,equity\nOTHER,60,equity\n"
    )
    before_records = _record_counts(client)
    response = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": fund_a,
                    "side": "sell",
                    "quantity": "10",
                    "price": "100",
                    "fee_amount": "2",
                    "currency": "USD",
                }
            ],
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["position_snapshot_ids"][account_id] == snapshot_id
    assert Decimal(result["before"]["indirect_lookthrough"]) == 1500
    assert Decimal(result["after"]["indirect_lookthrough"]) == 500
    assert Decimal(result["after"]["residual"]) == 1998
    assert Decimal(result["before"]["shared_indirect_amount"]) == 1500
    acme_overlap = next(
        row for row in result["before"]["overlap_rows"] if row["label"] == "ACME"
    )
    assert acme_overlap["fund_count"] == 2
    assert Decimal(acme_overlap["shared_indirect_amount"]) == 700
    assert result["after"]["overlap_rows"] == []
    assert Decimal(result["after"]["included_valued_nav"]) == 2498
    assert result["cash"][0]["cash_after"] == "1998.0000000000"
    assert _record_counts(client) == before_records


def test_cash_assumption_is_explicit_and_foreign_trade_is_rejected(
    scenario_client: TestClient,
) -> None:
    client = scenario_client
    account_id = _account(client)
    foreign_id = client.post(
        "/v1/securities",
        json={
            "security_type": "equity",
            "display_ticker": "EURX",
            "name": "Synthetic foreign equity",
            "currency": "EUR",
        },
    ).json()["id"]
    cash_id = _security(client, "CASH", "cash")
    _positions(client, account_id, [(cash_id, "0", None)])
    foreign = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[
                {
                    "account_id": account_id,
                    "security_id": foreign_id,
                    "side": "buy",
                    "quantity": "1",
                    "price": "10",
                    "currency": "EUR",
                }
            ],
            cash_changes=[
                {
                    "account_id": account_id,
                    "amount": "10",
                    "currency": "USD",
                    "label": "Explicit synthetic cash contribution",
                }
            ],
        ),
    )
    assert foreign.status_code == 422
    assert "USD securities" in foreign.json()["detail"]

    cash_only = client.post(
        "/v1/simulations/portfolio",
        json=_payload(
            account_id,
            trades=[],
            cash_changes=[
                {
                    "account_id": account_id,
                    "amount": "10",
                    "currency": "USD",
                    "label": "Explicit synthetic cash contribution",
                }
            ],
        ),
    )
    assert cash_only.status_code == 200, cash_only.text
    assert (
        cash_only.json()["cash_changes"][0]["label"]
        == "Explicit synthetic cash contribution"
    )
    assert cash_only.json()["cash"][0]["cash_after"] == "10.0000000000"
