"""Synthetic read-only runway and purchase planning scenarios."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.db.models import (
    AccountBalanceObservation,
    Base,
    FinancialTransaction,
    InvestmentEvent,
    PositionSnapshot,
)
from app.main import create_app


@pytest.fixture
def planning_client(
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


def _account(client: TestClient, name: str, account_type: str) -> str:
    response = client.post(
        "/v1/accounts",
        json={
            "name": name,
            "account_type": account_type,
            "base_currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])


def _security(client: TestClient, ticker: str, security_type: str) -> str:
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


def _balance(
    client: TestClient,
    account_id: str,
    amount: str,
    *,
    kind: str = "asset",
    currency: str = "USD",
) -> None:
    response = client.post(
        "/v1/finance/balances",
        json={
            "account_id": account_id,
            "as_of": date.today().isoformat(),
            "balance_kind": kind,
            "amount": amount,
            "currency": currency,
            "source": "Synthetic planning balance",
            "quality_status": "reported",
            "idempotency_key": f"planning-balance-{account_id}-{kind}-{currency}",
        },
    )
    assert response.status_code == 201, response.text


def _positions(
    client: TestClient,
    account_id: str,
    rows: list[tuple[str, str, str | None]],
) -> None:
    response = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": date.today().isoformat(),
            "positions": [
                {
                    "security_id": security_id,
                    "quantity": quantity,
                    "currency": "USD",
                    **({"reported_price": price} if price is not None else {}),
                }
                for security_id, quantity, price in rows
            ],
        },
    )
    assert response.status_code == 200, response.text


def _request(
    account_ids: list[str],
    *,
    horizon: int = 3,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "account_ids": account_ids,
        "as_of": date.today().isoformat(),
        "horizon_months": horizon,
        "history_months": 3,
        "monthly_income": "1000",
        "monthly_income_source": "Synthetic income assumption",
        "monthly_expenses": "500",
        "monthly_expenses_source": "Synthetic expense budget",
        "monthly_dividends": "25",
        "monthly_dividends_source": "Synthetic dividend estimate",
        "sensitivity_percent": "10",
        "scenario_label": "Synthetic plan",
        **extra,
    }


def _last_full_month_end() -> date:
    first = date(date.today().year, date.today().month, 1)
    return first - timedelta(days=1)


def _record_counts(client: TestClient) -> tuple[int, int, int, int]:
    factory = cast(Any, client.app).state.session_factory
    with factory() as session:
        return tuple(
            int(session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (
                AccountBalanceObservation,
                FinancialTransaction,
                InvestmentEvent,
                PositionSnapshot,
            )
        )  # type: ignore[return-value]


def test_monthly_projection_uses_explicit_inputs_and_scheduled_purchase(
    planning_client: TestClient,
) -> None:
    client = planning_client
    account_id = _account(client, "Synthetic checking", "checking")
    _balance(client, account_id, "1000")
    history_date = _last_full_month_end().isoformat()
    income = client.post(
        "/v1/transactions/manual",
        json={
            "account_id": account_id,
            "posted_date": history_date,
            "amount": "1200",
            "currency": "USD",
            "description": "Synthetic payroll",
            "classification": "income",
            "idempotency_key": "planning-payroll",
        },
    )
    assert income.status_code == 201, income.text
    expense = client.post(
        "/v1/transactions/manual",
        json={
            "account_id": account_id,
            "posted_date": history_date,
            "amount": "-500",
            "currency": "USD",
            "description": "Synthetic rent",
            "classification": "expense",
            "idempotency_key": "planning-rent",
        },
    )
    assert expense.status_code == 201, expense.text
    dividend = client.post(
        "/v1/portfolio/history/events",
        json={
            "account_id": account_id,
            "event_type": "dividend",
            "effective_date": history_date,
            "cash_amount": "30",
            "currency": "USD",
            "source_label": "Synthetic dividend statement",
            "quality_status": "reported",
            "idempotency_key": "planning-dividend",
        },
    )
    assert dividend.status_code == 201, dividend.text
    before = _record_counts(client)

    response = client.post(
        "/v1/planning/scenarios",
        json=_request(
            [account_id],
            recurring_changes=[{"amount": "-50", "label": "New monthly bill"}],
            one_time_changes=[
                {
                    "month_offset": 2,
                    "change_type": "purchase",
                    "amount": "-2000",
                    "label": "Used vehicle purchase",
                }
            ],
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["projection_status"] == "available"
    assert result["starting_cash_source"] == "observed_usd_cash"
    assert result["starting_cash_usd"] == "1000.0000000000"
    assert account_id in result["account_balance_ids"]
    assert result["account_balance_revisions"][account_id] == 1
    assert result["transaction_history"][0]["income_total"] == "1200.0000000000"
    assert result["transaction_history"][0]["expenses_total"] == "500.0000000000"
    assert result["dividend_history"][0]["total"] == "30.0000000000"
    base = next(case for case in result["cases"] if case["case"] == "base")
    assert [month["ending_cash"] for month in base["months"]] == [
        "1475.0000000000",
        "-50.0000000000",
        "425.0000000000",
    ]
    assert base["months"][0]["income"] == "1000.0000000000"
    assert base["shortfall_month"] == 2
    assert base["runway_status"] == "shortfall_within_horizon"
    conservative = next(
        case for case in result["cases"] if case["case"] == "conservative"
    )
    optimistic = next(case for case in result["cases"] if case["case"] == "optimistic")
    assert conservative["months"][0]["ending_cash"] == "1322.5000000000"
    assert optimistic["months"][0]["ending_cash"] == "1627.5000000000"
    assert result["canonical_records_mutated"] is False
    assert result["persisted"] is False
    assert result["scenario_fingerprint"]
    assert _record_counts(client) == before


def test_restricted_assets_liabilities_and_unknown_cash_stay_separate(
    planning_client: TestClient,
) -> None:
    client = planning_client
    ira_id = _account(client, "Synthetic IRA", "ira")
    taxable_id = _account(client, "Synthetic taxable", "taxable")
    card_id = _account(client, "Synthetic credit card", "credit_card")
    ira_cash = _security(client, "IRA-CASH", "cash")
    ira_equity = _security(client, "IRA-EQ", "equity")
    taxable_equity = _security(client, "TAX-EQ", "equity")
    _positions(client, ira_id, [(ira_cash, "1000", None), (ira_equity, "10", "100")])
    _positions(client, taxable_id, [(taxable_equity, "10", "100")])
    _balance(client, card_id, "500", kind="liability")

    request = _request(
        [ira_id, taxable_id, card_id],
        monthly_income="0",
        monthly_expenses="100",
        monthly_dividends="0",
        one_time_changes=[],
    )
    response = client.post("/v1/planning/scenarios", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    usd = next(
        line for line in result["currency_balances"] if line["currency"] == "USD"
    )
    assert Decimal(usd["restricted_assets"]) == Decimal("2000")
    assert Decimal(usd["investment_assets"]) == Decimal("1000")
    assert Decimal(usd["liabilities"]) == Decimal("-500")
    assert result["liquid_cash_observed_usd"] == "0"
    assert result["starting_cash_coverage"] == "incomplete"
    assert result["projection_status"] == "incomplete"
    assert any("no USD cash line" in warning for warning in result["warnings"])
    equity_line = next(
        line for line in result["balances"] if line["detail"] == "IRA-EQ"
    )
    assert equity_line["as_of"] == date.today().isoformat()
    assert equity_line["price_as_of"] is not None
    assert all(
        case["runway_status"] == "coverage_incomplete" for case in result["cases"]
    )

    override = client.post(
        "/v1/planning/scenarios",
        json={**request, "starting_cash_override": "5000"},
    )
    assert override.status_code == 200, override.text
    assumed = override.json()
    assert assumed["starting_cash_source"] == "user_override"
    assert assumed["starting_cash_usd"] == "5000"
    assert assumed["projection_status"] == "available"
    assert assumed["balance_sheet_complete"] is False


def test_empty_history_does_not_create_an_income_or_dividend_assumption(
    planning_client: TestClient,
) -> None:
    client = planning_client
    account_id = _account(client, "Synthetic checking", "checking")
    _balance(client, account_id, "300")
    response = client.post(
        "/v1/planning/scenarios",
        json=_request(
            [account_id],
            horizon=2,
            monthly_income="0",
            monthly_expenses="0",
            monthly_dividends="0",
            sensitivity_percent="0",
            one_time_changes=[],
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["transaction_history"] == []
    assert result["dividend_history"] == []
    assert any(
        "No eligible published transactions" in gap for gap in result["history_gaps"]
    )
    assert any("No reviewed dividend events" in gap for gap in result["history_gaps"])
    assert [month["income"] for month in result["cases"][1]["months"]] == [
        "0.0000000000",
        "0.0000000000",
    ]
    assert [month["dividends"] for month in result["cases"][1]["months"]] == [
        "0.0000000000",
        "0.0000000000",
    ]


def test_sensitivity_is_bounded_and_future_dated_plans_are_rejected(
    planning_client: TestClient,
) -> None:
    client = planning_client
    account_id = _account(client, "Synthetic checking", "checking")
    _balance(client, account_id, "1000")
    invalid_sensitivity = client.post(
        "/v1/planning/scenarios",
        json=_request([account_id], sensitivity_percent="60"),
    )
    assert invalid_sensitivity.status_code == 422
    future = client.post(
        "/v1/planning/scenarios",
        json={
            **_request([account_id]),
            "as_of": (date.today() + timedelta(days=1)).isoformat(),
        },
    )
    assert future.status_code == 422
