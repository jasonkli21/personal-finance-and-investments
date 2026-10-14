from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.discretionary_budget_contracts import MonthlyDiscretionaryBudgetWrite
from app.db.models import Base, MonthlyDiscretionaryBudget
from app.domains.discretionary_budget import (
    BudgetConflict,
    replace_monthly_discretionary_budget,
)
from app.domains.finance_context import FinanceContextNotFound, read_finance_context
from app.integrations.finance_context import (
    FinanceContextEntityReference,
    FinanceContextReadRequest,
)
from app.main import create_app


@pytest.fixture
def budget_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("AUTH_ENABLED", "false")
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with TestClient(create_app(engine=engine)) as client:
        yield client
    engine.dispose()


def test_monthly_budget_write_and_read_keep_consent_explicit(
    budget_client: TestClient,
) -> None:
    response = budget_client.put(
        "/v1/finance/discretionary-budgets/2026-11",
        json={
            "expected_revision": 0,
            "amount": "850.50",
            "currency": "USD",
            "share_with_shopping": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == "850.50"
    assert response.json()["revision"] == 1
    assert response.json()["share_with_shopping"] is True

    changed = budget_client.put(
        "/v1/finance/discretionary-budgets/2026-11",
        json={
            "expected_revision": 1,
            "amount": "900",
            "currency": "USD",
            "share_with_shopping": False,
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 2
    assert changed.json()["share_with_shopping"] is False

    read = budget_client.get("/v1/finance/discretionary-budgets/2026-11")
    assert read.status_code == 200
    assert read.json()["amount"] == "900.00"
    assert read.json()["share_with_shopping"] is False


def test_monthly_budget_api_rejects_stale_revision_and_invalid_period(
    budget_client: TestClient,
) -> None:
    created = budget_client.put(
        "/v1/finance/discretionary-budgets/2026-11",
        json={
            "expected_revision": 0,
            "amount": "0",
            "currency": "USD",
            "share_with_shopping": False,
        },
    )
    assert created.status_code == 200

    stale = budget_client.put(
        "/v1/finance/discretionary-budgets/2026-11",
        json={
            "expected_revision": 0,
            "amount": "1",
            "currency": "USD",
            "share_with_shopping": True,
        },
    )
    assert stale.status_code == 409
    assert (
        budget_client.put(
            "/v1/finance/discretionary-budgets/2026-13",
            json={
                "expected_revision": 0,
                "amount": "1",
                "currency": "USD",
                "share_with_shopping": True,
            },
        ).status_code
        == 422
    )


def test_budget_contract_requires_strict_amount_currency_and_consent() -> None:
    with pytest.raises(ValueError):
        MonthlyDiscretionaryBudgetWrite.model_validate(
            {"expected_revision": 0, "amount": "-1", "currency": "USD"}
        )
    with pytest.raises(ValueError):
        MonthlyDiscretionaryBudgetWrite.model_validate(
            {"expected_revision": 0, "amount": "12.345", "currency": "USD"}
        )
    with pytest.raises(ValueError):
        MonthlyDiscretionaryBudgetWrite.model_validate(
            {"expected_revision": 0, "amount": "12", "currency": "usd"}
        )
    default = MonthlyDiscretionaryBudgetWrite.model_validate(
        {"expected_revision": 0, "amount": "12", "currency": "USD"}
    )
    assert default.share_with_shopping is False


def test_budget_revision_is_checked_under_domain_transaction() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            row = replace_monthly_discretionary_budget(
                session,
                period="2026-11",
                expected_revision=0,
                amount=Decimal("100.00"),
                currency="CAD",
                share_with_shopping=True,
            )
            assert row.revision == 1
        with Session(engine) as session, session.begin():
            with pytest.raises(BudgetConflict):
                replace_monthly_discretionary_budget(
                    session,
                    period="2026-11",
                    expected_revision=0,
                    amount=Decimal("120.00"),
                    currency="CAD",
                    share_with_shopping=True,
                )
        with Session(engine) as session:
            current = session.scalar(select(MonthlyDiscretionaryBudget))
            assert current is not None
            assert current.amount == Decimal("100.00")
            assert current.revision == 1
    finally:
        engine.dispose()


def test_budget_context_export_is_narrow_and_rechecks_sharing_consent() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session, session.begin():
            budget = replace_monthly_discretionary_budget(
                session,
                period="2026-11",
                expected_revision=0,
                amount=Decimal("850.50"),
                currency="USD",
                share_with_shopping=True,
            )
            budget_id = budget.id
        export = FinanceContextReadRequest(
            operation="current",
            purpose="shopping_discretionary_budget",
            destination_application_id="shopping",
            entity_refs=(
                FinanceContextEntityReference(
                    entity_type="discretionary_budget", entity_id=str(budget_id)
                ),
            ),
            fields=("amount", "currency", "period"),
            max_results=1,
            max_bytes=4096,
        )
        with Session(engine) as session:
            response = read_finance_context(
                session, export, principal_scope_id="verified-finance-scope"
            )
        record = response.items[0]
        values = record.payload["discretionary_budget"]
        assert set(values) == {"amount", "currency", "period"}
        assert values["amount"].value == "850.50"
        assert values["amount"].currency == "USD"
        assert values["currency"].value == "USD"
        assert values["period"].value == "2026-11"
        assert (
            record.permission_dependencies[0].purpose == "shopping_discretionary_budget"
        )

        verify = export.model_copy(
            update={"operation": "verify", "fields": ("permission_version",)}
        )
        with Session(engine) as session:
            verified = read_finance_context(
                session, verify, principal_scope_id="verified-finance-scope"
            )
        assert verified.items[0].source_version == record.source_version

        with Session(engine) as session, session.begin():
            current = session.get(MonthlyDiscretionaryBudget, budget_id)
            assert current is not None
            current.share_with_shopping = False
            current.revision += 1
        with Session(engine) as session:
            with pytest.raises(FinanceContextNotFound):
                read_finance_context(
                    session, export, principal_scope_id="verified-finance-scope"
                )
        with Session(engine) as session:
            with pytest.raises(FinanceContextNotFound):
                read_finance_context(
                    session, verify, principal_scope_id="verified-finance-scope"
                )
    finally:
        engine.dispose()


def test_budget_export_contract_rejects_other_fields_and_destination() -> None:
    reference = FinanceContextEntityReference(
        entity_type="discretionary_budget",
        entity_id="d3a1f491-a9d7-4c95-b2a4-6d85b7568186",
    )
    with pytest.raises(ValueError):
        FinanceContextReadRequest(
            operation="current",
            purpose="shopping_discretionary_budget",
            destination_application_id="shopping",
            entity_refs=(reference,),
            fields=("amount", "currency", "period", "account_summary"),
            max_results=1,
            max_bytes=4096,
        )
    with pytest.raises(ValueError):
        FinanceContextReadRequest(
            operation="current",
            purpose="shopping_discretionary_budget",
            entity_refs=(reference,),
            fields=("amount", "currency", "period"),
            max_results=1,
            max_bytes=4096,
        )
