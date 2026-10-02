"""Synthetic API coverage for accounts and revision-checked manual positions."""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.contracts import PositionReplace
from app.db.models import Base, PositionSnapshot, Security
from app.domains import portfolio
from app.main import create_app


@pytest.fixture
def api_context(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, UUID, UUID]]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    security_id = uuid4()
    cash_id = uuid4()
    with Session(engine) as session:
        session.add(
            Security(
                id=security_id,
                security_type="equity",
                display_ticker="ACME",
                name="Acme Synthetic Corp.",
                currency="USD",
            )
        )
        session.add(
            Security(
                id=cash_id,
                security_type="cash",
                display_ticker=None,
                name="Synthetic US Dollar Cash",
                currency="USD",
            )
        )
        session.commit()

    app = create_app(engine=engine)
    with TestClient(app) as client:
        yield client, security_id, cash_id


def create_account(client: TestClient, name: str) -> dict[str, Any]:
    response = client.post(
        "/v1/accounts",
        json={"name": name, "account_type": "taxable", "base_currency": "USD"},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def position_payload(
    security_id: UUID,
    *,
    expected_revision: int | None,
    quantity: str = "2.5",
    price: str | None = "10.00",
    currency: str = "USD",
    effective_date: str = "2026-09-30",
) -> dict[str, Any]:
    return {
        "expected_revision": expected_revision,
        "effective_date": effective_date,
        "positions": [
            {
                "security_id": str(security_id),
                "quantity": quantity,
                "reported_price": price,
                "currency": currency,
            }
        ],
    }


def test_account_crud_and_local_security_resolution(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, _security_id, _cash_id = api_context
    first = create_account(client, "Synthetic taxable")
    second = create_account(client, "Synthetic Roth")

    assert [account["id"] for account in client.get("/v1/accounts").json()] == [
        first["id"],
        second["id"],
    ]
    updated = client.patch(
        f"/v1/accounts/{first['id']}", json={"name": "Renamed taxable"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed taxable"
    other_account = next(
        account
        for account in client.get("/v1/accounts").json()
        if account["id"] == second["id"]
    )
    assert other_account["name"] == "Synthetic Roth"

    match = client.get("/v1/securities/resolve", params={"q": "acm"}).json()
    assert match["status"] == "resolved"
    assert match["matches"][0]["display_ticker"] == "ACME"
    unknown = client.get("/v1/securities/resolve", params={"q": "zzzz"}).json()
    assert unknown == {"status": "unknown", "matches": []}

    schema = client.get("/openapi.json").json()
    assert "/v1/accounts/{account_id}/positions" in schema["paths"]
    quantity_schema = schema["components"]["schemas"]["PositionInput"]["properties"][
        "quantity"
    ]
    assert quantity_schema["type"] == "string"
    conflict_schema = schema["paths"]["/v1/accounts/{account_id}/positions"]["put"][
        "responses"
    ]["409"]["content"]["application/json"]["schema"]
    assert conflict_schema["$ref"] == "#/components/schemas/ErrorResponse"


def test_manual_positions_are_account_scoped_and_revision_checked(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, security_id, _cash_id = api_context
    first = create_account(client, "Synthetic account one")
    second = create_account(client, "Synthetic account two")

    first_saved = client.put(
        f"/v1/accounts/{first['id']}/positions",
        json=position_payload(security_id, expected_revision=None),
    )
    second_saved = client.put(
        f"/v1/accounts/{second['id']}/positions",
        json=position_payload(
            security_id, expected_revision=None, quantity="1", price="20"
        ),
    )
    assert first_saved.status_code == second_saved.status_code == 200
    assert first_saved.json()["positions"][0]["reported_value"] == "25.0000000000"
    assert second_saved.json()["positions"][0]["reported_value"] == "20.0000000000"

    competing_first_save = client.put(
        f"/v1/accounts/{first['id']}/positions",
        json=position_payload(
            security_id,
            expected_revision=None,
            effective_date="2026-10-01",
        ),
    )
    assert competing_first_save.status_code == 409

    updated = client.put(
        f"/v1/accounts/{first['id']}/positions",
        json=position_payload(
            security_id,
            expected_revision=1,
            quantity="3",
            price="11.25",
            effective_date="2026-10-01",
        ),
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] == 2
    assert updated.json()["effective_date"] == "2026-10-01"
    assert updated.json()["positions"][0]["reported_value"] == "33.7500000000"

    stale = client.put(
        f"/v1/accounts/{first['id']}/positions",
        json=position_payload(security_id, expected_revision=1, quantity="9"),
    )
    assert stale.status_code == 409
    first_read = client.get(f"/v1/accounts/{first['id']}/positions").json()["snapshot"]
    second_read = client.get(f"/v1/accounts/{second['id']}/positions").json()[
        "snapshot"
    ]
    assert first_read["revision"] == 2
    assert first_read["positions"][0]["quantity"] == "3.0000000000"
    assert second_read["revision"] == 1
    assert second_read["positions"][0]["quantity"] == "1.0000000000"


def test_missing_prices_and_invalid_replacements_are_preserved_safely(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, security_id, _cash_id = api_context
    account = create_account(client, "Synthetic unpriced")
    path = f"/v1/accounts/{account['id']}/positions"
    missing_price = client.put(
        path,
        json=position_payload(
            security_id, expected_revision=None, quantity="0", price=None
        ),
    )
    assert missing_price.status_code == 200
    line = missing_price.json()["positions"][0]
    assert line["reported_value"] is None
    assert line["quality_status"] == "unavailable"

    invalid = client.put(
        path,
        json=position_payload(
            security_id,
            expected_revision=1,
            quantity="10",
            price="12",
            currency="EUR",
        ),
    )
    assert invalid.status_code == 422
    unchanged = client.get(path).json()["snapshot"]
    assert unchanged["revision"] == 1
    assert unchanged["positions"][0]["quantity"] == "0E-10"

    numeric_json = position_payload(security_id, expected_revision=1)
    numeric_json["positions"][0]["quantity"] = 2.5
    assert client.put(path, json=numeric_json).status_code == 422

    archived = client.patch(f"/v1/accounts/{account['id']}", json={"active": False})
    assert archived.status_code == 200
    assert (
        client.put(
            path,
            json=position_payload(security_id, expected_revision=1),
        ).status_code
        == 409
    )


def test_invalid_effective_date_and_unknown_security_return_safe_errors(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, _security_id, _cash_id = api_context
    account = create_account(client, "Synthetic invalid")
    path = f"/v1/accounts/{account['id']}/positions"
    unknown = position_payload(uuid4(), expected_revision=None)
    assert client.put(path, json=unknown).status_code == 422

    malformed = position_payload(uuid4(), expected_revision=None)
    malformed["effective_date"] = "yesterday"
    assert client.put(path, json=malformed).status_code == 422

    assert client.get(f"/v1/accounts/{uuid4()}/positions").status_code == 404


def test_cash_is_saved_as_an_explicit_currency_balance(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, _security_id, cash_id = api_context
    account = create_account(client, "Synthetic cash account")
    payload = position_payload(
        cash_id,
        expected_revision=None,
        quantity="123.45",
        price=None,
    )
    saved = client.put(
        f"/v1/accounts/{account['id']}/positions",
        json=payload,
    )
    assert saved.status_code == 200
    line = saved.json()["positions"][0]
    assert line["reported_value"] == "123.4500000000"
    assert line["reported_price"] is None
    assert line["price_as_of"] is None


def test_manual_valuation_rounds_half_up_to_numeric_scale(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, security_id, _cash_id = api_context
    account = create_account(client, "Synthetic rounding account")
    response = client.put(
        f"/v1/accounts/{account['id']}/positions",
        json=position_payload(
            security_id,
            expected_revision=None,
            quantity="1.5",
            price="1.0000000001",
        ),
    )

    assert response.status_code == 200
    assert response.json()["positions"][0]["reported_value"] == "1.5000000002"


def test_two_tabs_and_background_refetch_keep_the_draft_base_revision(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, security_id, _cash_id = api_context
    account = create_account(client, "Synthetic concurrent account")
    path = f"/v1/accounts/{account['id']}/positions"

    first_tab_initial = client.get(path).json()
    draft_base_revision = first_tab_initial["current_revision"]
    assert draft_base_revision == 0

    second_tab_save = client.put(
        path,
        json=position_payload(
            security_id,
            expected_revision=first_tab_initial["current_revision"],
            quantity="4",
            price="12",
        ),
    )
    assert second_tab_save.status_code == 200
    assert second_tab_save.json()["revision"] == 1

    # Model a focus-triggered refresh while the first tab still owns a dirty
    # draft. The draft keeps its captured base even though server state is new.
    refreshed = client.get(path).json()
    assert refreshed["current_revision"] == 1
    first_tab_save = client.put(
        path,
        json=position_payload(
            security_id,
            expected_revision=draft_base_revision,
            quantity="9",
            price="13",
        ),
    )
    assert first_tab_save.status_code == 409
    current = client.get(path).json()
    assert current["current_revision"] == 1
    assert current["snapshot"]["positions"][0]["quantity"] == "4.0000000000"


def test_same_date_replacement_appends_and_retains_previous_snapshot_lines(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, security_id, _cash_id = api_context
    account = create_account(client, "Synthetic snapshot history")
    path = f"/v1/accounts/{account['id']}/positions"
    first = client.put(
        path,
        json=position_payload(
            security_id, expected_revision=None, quantity="2", price="10"
        ),
    )
    second = client.put(
        path,
        json=position_payload(
            security_id, expected_revision=1, quantity="3", price="11"
        ),
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["revision"] == 1
    assert second.json()["revision"] == 2

    factory = cast(Any, client.app).state.session_factory
    with factory() as session:
        earlier = session.get(PositionSnapshot, UUID(first.json()["id"]))
        assert earlier is not None
        assert earlier.status == "superseded"
        old_lines = portfolio._snapshot_lines(session, earlier.id)
        assert len(old_lines) == 1
        assert old_lines[0][0].quantity == Decimal("2.0000000000")


def test_maximum_individual_inputs_return_safe_422_before_any_write(
    api_context: tuple[TestClient, UUID, UUID],
) -> None:
    client, security_id, _cash_id = api_context
    account = create_account(client, "Synthetic overflow account")
    path = f"/v1/accounts/{account['id']}/positions"
    unsafe = position_payload(
        security_id,
        expected_revision=None,
        quantity="999999999999999999.9999999999",
        price="99999999999999.9999999999",
    )
    rejected = client.put(path, json=unsafe)
    assert rejected.status_code == 422
    assert rejected.json() == {
        "detail": "The reported value exceeds the supported decimal precision."
    }
    after = client.get(path).json()
    assert after["current_revision"] == 0
    assert after["snapshot"] is None


def test_manual_valuation_rounding_boundary_and_failed_transaction_rollback(
    api_context: tuple[TestClient, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, security_id, _cash_id = api_context
    account = create_account(client, "Synthetic rollback account")
    path = f"/v1/accounts/{account['id']}/positions"
    first = client.put(
        path,
        json=position_payload(
            security_id,
            expected_revision=None,
            quantity="0.0000000001",
            price="0.5000000000",
        ),
    )
    assert first.status_code == 200
    assert Decimal(first.json()["positions"][0]["reported_value"]) == Decimal(
        "0.0000000001"
    )

    def fail_after_snapshot_flush(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic response assembly failure")

    factory = cast(Any, client.app).state.session_factory
    with monkeypatch.context() as patcher:
        patcher.setattr(portfolio, "_snapshot_lines", fail_after_snapshot_flush)
        with factory() as session, pytest.raises(RuntimeError, match="synthetic"):
            with session.begin():
                portfolio.replace_positions(
                    session,
                    UUID(account["id"]),
                    PositionReplace.model_validate(
                        position_payload(
                            security_id,
                            expected_revision=1,
                            quantity="8",
                            price="10",
                        )
                    ),
                )

    latest = client.get(path).json()
    assert latest["current_revision"] == 1
    assert latest["snapshot"]["id"] == first.json()["id"]
    assert Decimal(latest["snapshot"]["positions"][0]["quantity"]) == Decimal(
        "0.0000000001"
    )
