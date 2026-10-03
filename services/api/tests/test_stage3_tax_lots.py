"""Synthetic reviewed tax-lot imports and append-only adjustments."""

from collections.abc import Iterator
from pathlib import Path
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
def tax_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, UUID, UUID]]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    equity_id = uuid4()
    cash_id = uuid4()
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
    engine.dispose()


def _account(client: TestClient) -> str:
    response = client.post(
        "/v1/accounts",
        json={
            "name": "Synthetic taxable",
            "account_type": "taxable",
            "base_currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return cast(str, cast(dict[str, Any], response.json())["id"])


def _accept_position(
    client: TestClient, account_id: str, security_id: UUID, quantity: str
) -> None:
    response = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": "2026-10-01",
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


def _upload(
    client: TestClient,
    account_id: str,
    content: bytes,
    *,
    key: str,
) -> Any:
    return client.post(
        "/v1/imports/tax-lots/preview",
        content=content,
        headers={
            "Content-Type": "text/csv",
            "X-Account-Id": account_id,
            "X-Source-Label": "Synthetic broker export",
            "X-Column-Mapping": (
                '{"ticker":"Symbol","source_lot_id":"Lot ID",'
                '"acquired_at":"Acquired","initial_quantity":"Original Shares",'
                '"remaining_quantity":"Shares", "initial_basis":"Original Basis",'
                '"remaining_basis":"Basis", "basis_currency":"Currency"}'
            ),
            "X-File-Name": "synthetic-lots.csv",
            "Idempotency-Key": key,
        },
    )


def test_review_publish_is_idempotent_and_preserves_individual_lots(
    tax_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, equity_id, _cash_id = tax_client
    account_id = _account(client)
    _accept_position(client, account_id, equity_id, "10")
    csv_bytes = (
        b"Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,Currency\n"
        b"ACME,LOT-A,2020-02-03,4,4,200,200,USD\n"
        b"ACME,LOT-B,2021-04-05,6,6,360,360,USD\n"
    )
    staged = _upload(client, account_id, csv_bytes, key="stage3-lots-001")
    assert staged.status_code == 201, staged.text
    first = staged.json()
    assert first["row_count"] == 2
    assert first["status"] == "review"

    review_response = client.get(f"/v1/tax-lot-imports/{first['id']}")
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    assert review["quantity_differences"][0]["difference"] == "0E-10"
    assert [row["acquired_at"] for row in review["rows"]] == [
        "2020-02-03",
        "2021-04-05",
    ]

    published = client.post(
        f"/v1/tax-lot-imports/{first['id']}/publish",
        json={
            "expected_revision": review["review_revision"],
            "acknowledge_quantity_differences": False,
            "reason": "Synthetic exact quantity reconciliation",
        },
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    replay = client.post(
        f"/v1/tax-lot-imports/{first['id']}/publish",
        json={
            "expected_revision": review["review_revision"],
            "acknowledge_quantity_differences": False,
            "reason": "Idempotent publication replay",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["status"] == "published"

    lots_response = client.get("/v1/tax-lots", params={"account_id": account_id})
    assert lots_response.status_code == 200, lots_response.text
    lots = lots_response.json()
    assert len(lots) == 2
    assert (
        len(
            client.get(
                "/v1/tax-lots",
                params={"account_id": account_id, "quality_status": "reported"},
            ).json()
        )
        == 2
    )
    assert {(lot["acquired_at"], lot["remaining_basis"]) for lot in lots} == {
        ("2020-02-03", "200.0000000000"),
        ("2021-04-05", "360.0000000000"),
    }

    repeated = _upload(client, account_id, csv_bytes, key="stage3-lots-002")
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == first["id"]
    assert repeated.json()["duplicate"] is True
    assert (
        len(client.get("/v1/tax-lots", params={"account_id": account_id}).json()) == 2
    )

    adjustment_payload = {
        "adjustment_type": "correction",
        "quantity_delta": "-0.5",
        "basis_delta": "-25",
        "basis_currency": "USD",
        "effective_date": "2026-10-01",
        "source_label": "Synthetic correction evidence",
        "reason": "Synthetic fractional share disposition",
        "evidence_ref": "statement:line-8",
        "idempotency_key": "stage3-adjustment-001",
        "raw_values": {"source_note": "synthetic"},
    }
    adjusted = client.post(
        f"/v1/tax-lots/{lots[0]['id']}/adjustments", json=adjustment_payload
    )
    assert adjusted.status_code == 201, adjusted.text
    repeated_adjustment = client.post(
        f"/v1/tax-lots/{lots[0]['id']}/adjustments", json=adjustment_payload
    )
    assert repeated_adjustment.status_code == 201, repeated_adjustment.text
    assert repeated_adjustment.json()["id"] == adjusted.json()["id"]
    updated_lots = client.get("/v1/tax-lots", params={"account_id": account_id}).json()
    updated = next(lot for lot in updated_lots if lot["id"] == lots[0]["id"])
    assert updated["current_remaining_quantity"] == "3.5000000000"
    assert updated["current_remaining_basis"] == "175.0000000000"


def test_missing_fields_stay_unavailable_and_review_revision_is_enforced(
    tax_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, equity_id, _cash_id = tax_client
    account_id = _account(client)
    content = (
        b"Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,Currency\n"
        b"UNKNOWN,LOT-X,,,2,,2,\n"
    )
    staged = _upload(client, account_id, content, key="stage3-lots-003")
    assert staged.status_code == 201, staged.text
    review = client.get(f"/v1/tax-lot-imports/{staged.json()['id']}").json()
    row = review["rows"][0]
    assert row["row_status"] == "needs_review"
    assert row["acquired_at"] is None
    assert row["initial_quantity"] is None
    assert row["remaining_basis"] == "2.0000000000"
    assert row["basis_currency"] is None

    correction = client.patch(
        f"/v1/tax-lot-imports/{review['id']}/rows/{row['id']}",
        json={
            "expected_revision": review["review_revision"],
            "reason": "Matched against the synthetic source statement",
            "security_id": str(equity_id),
            "basis_currency": "USD",
        },
    )
    assert correction.status_code == 200, correction.text
    assert correction.json()["review_revision"] == review["review_revision"] + 1
    assert correction.json()["rows"][0]["row_status"] == "ready"

    stale = client.patch(
        f"/v1/tax-lot-imports/{review['id']}/rows/{row['id']}",
        json={
            "expected_revision": review["review_revision"],
            "reason": "Stale correction",
            "evidence_ref": "source:again",
        },
    )
    assert stale.status_code == 409

    stale_publish = client.post(
        f"/v1/tax-lot-imports/{review['id']}/publish",
        json={
            "expected_revision": review["review_revision"],
            "acknowledge_quantity_differences": True,
            "reason": "Stale publication after correction",
        },
    )
    assert stale_publish.status_code == 409

    published = client.post(
        f"/v1/tax-lot-imports/{review['id']}/publish",
        json={
            "expected_revision": correction.json()["review_revision"],
            "acknowledge_quantity_differences": True,
            "reason": "Acknowledged unavailable position reconciliation",
        },
    )
    assert published.status_code == 200, published.text
    lots = client.get("/v1/tax-lots", params={"account_id": account_id}).json()
    assert len(lots) == 1
    assert lots[0]["acquired_at"] is None
    assert lots[0]["initial_quantity"] is None
    assert lots[0]["initial_basis"] is None
    assert lots[0]["remaining_basis"] == "2.0000000000"
    assert lots[0]["basis_currency"] == "USD"
    assert (
        len(
            client.get(
                "/v1/tax-lots",
                params={"account_id": account_id, "quality_status": "incomplete"},
            ).json()
        )
        == 1
    )


def test_unsupported_cash_lots_and_unacknowledged_gaps_stay_blocked(
    tax_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, _equity_id, _cash_id = tax_client
    account_id = _account(client)
    content = (
        b"Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,Currency\n"
        b"CASH,CASH-LOT,2020-01-01,1,1,1,1,USD\n"
    )
    staged = _upload(client, account_id, content, key="stage3-lots-004")
    assert staged.status_code == 201, staged.text
    review = client.get(f"/v1/tax-lot-imports/{staged.json()['id']}").json()
    assert review["rows"][0]["row_status"] == "needs_review"
    assert (
        review["rows"][0]["diagnostics"]["security_type"] == "unsupported_for_tax_lots"
    )
    blocked = client.post(
        f"/v1/tax-lot-imports/{review['id']}/publish",
        json={
            "expected_revision": review["review_revision"],
            "acknowledge_quantity_differences": True,
            "reason": "Should remain blocked",
        },
    )
    assert blocked.status_code == 422
    assert client.get("/v1/tax-lots", params={"account_id": account_id}).json() == []


def test_backdated_adjustment_cannot_make_a_later_lot_state_negative(
    tax_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, equity_id, _cash_id = tax_client
    account_id = _account(client)
    _accept_position(client, account_id, equity_id, "10")
    csv_bytes = (
        b"Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,Currency\n"
        b"ACME,CHRONO,2020-02-03,10,10,200,200,USD\n"
    )
    staged = _upload(client, account_id, csv_bytes, key="stage3-chrono-001")
    review = client.get(f"/v1/tax-lot-imports/{staged.json()['id']}").json()
    published = client.post(
        f"/v1/tax-lot-imports/{review['id']}/publish",
        json={
            "expected_revision": review["review_revision"],
            "acknowledge_quantity_differences": False,
            "reason": "Publish source lot",
        },
    )
    assert published.status_code == 200, published.text
    lot_id = client.get("/v1/tax-lots", params={"account_id": account_id}).json()[0][
        "id"
    ]
    common = {
        "adjustment_type": "correction",
        "basis_currency": "USD",
        "source_label": "Synthetic corrections",
        "reason": "Synthetic chronological-state regression",
    }
    later = client.post(
        f"/v1/tax-lots/{lot_id}/adjustments",
        json={
            **common,
            "quantity_delta": "-6",
            "effective_date": "2026-09-20",
            "idempotency_key": "chrono-later",
        },
    )
    assert later.status_code == 201, later.text
    same_day = client.post(
        f"/v1/tax-lots/{lot_id}/adjustments",
        json={
            **common,
            "quantity_delta": "1",
            "effective_date": "2026-09-20",
            "idempotency_key": "chrono-same-day",
        },
    )
    assert same_day.status_code == 201, same_day.text
    backdated = client.post(
        f"/v1/tax-lots/{lot_id}/adjustments",
        json={
            **common,
            "quantity_delta": "-6",
            "effective_date": "2026-09-01",
            "idempotency_key": "chrono-earlier",
        },
    )
    assert backdated.status_code == 422
    assert "negative" in backdated.json()["detail"]


def test_import_reviewed_before_duplicate_publication_skips_new_duplicate_safely(
    tax_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, equity_id, _cash_id = tax_client
    account_id = _account(client)
    _accept_position(client, account_id, equity_id, "2")
    first_csv = (
        b"Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,"
        b"Currency,Note\n"
        b"ACME,SHARED,2020-02-03,2,2,100,100,USD,first\n"
    )
    second_csv = first_csv.replace(b"first", b"second")
    first = _upload(client, account_id, first_csv, key="stage3-identity-first")
    second = _upload(client, account_id, second_csv, key="stage3-identity-second")
    assert first.status_code == second.status_code == 201
    first_review = client.get(f"/v1/tax-lot-imports/{first.json()['id']}").json()
    second_review = client.get(f"/v1/tax-lot-imports/{second.json()['id']}").json()
    assert first_review["rows"][0]["row_status"] == "ready"
    assert second_review["rows"][0]["row_status"] == "ready"
    for review in (first_review, second_review):
        if review is first_review:
            response = client.post(
                f"/v1/tax-lot-imports/{review['id']}/publish",
                json={
                    "expected_revision": review["review_revision"],
                    "acknowledge_quantity_differences": False,
                    "reason": "Publish shared source lot once",
                },
            )
            assert response.status_code == 200, response.text
        else:
            response = client.post(
                f"/v1/tax-lot-imports/{review['id']}/publish",
                json={
                    "expected_revision": review["review_revision"],
                    "acknowledge_quantity_differences": False,
                    "reason": "Skip source identity already published",
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["rows"][0]["row_status"] == "duplicate"
    assert (
        len(client.get("/v1/tax-lots", params={"account_id": account_id}).json()) == 1
    )


def test_overlong_source_identifier_stays_raw_and_can_be_corrected(
    tax_client: tuple[TestClient, UUID, UUID],
) -> None:
    client, _equity_id, _cash_id = tax_client
    account_id = _account(client)
    source_lot_id = "L" * 201
    content = (
        "Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,Currency\n"
        f"ACME,{source_lot_id},2020-01-01,2,1,50,25,USD\n"
    ).encode()
    staged = _upload(client, account_id, content, key="stage3-lots-005")
    assert staged.status_code == 201, staged.text
    review = client.get(f"/v1/tax-lot-imports/{staged.json()['id']}").json()
    row = review["rows"][0]
    assert row["row_status"] == "needs_review"
    assert row["raw_source_lot_id"] is None
    assert row["raw_payload"]["Lot ID"] == source_lot_id
    assert row["diagnostics"]["source_lot_id"] == "too_long"

    corrected = client.patch(
        f"/v1/tax-lot-imports/{review['id']}/rows/{row['id']}",
        json={
            "expected_revision": review["review_revision"],
            "reason": "Shortened to the broker's source lot identifier",
            "source_lot_id": "LOT-VALID",
        },
    )
    assert corrected.status_code == 200, corrected.text
    updated_row = corrected.json()["rows"][0]
    assert updated_row["row_status"] == "ready"
    assert updated_row["raw_source_lot_id"] == "LOT-VALID"
    assert updated_row["raw_payload"]["Lot ID"] == source_lot_id


def test_publication_honors_lower_configured_safe_batch(
    tax_client: tuple[TestClient, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, equity_id, _cash_id = tax_client
    account_id = _account(client)
    _accept_position(client, account_id, equity_id, "2")
    content = (
        b"Symbol,Lot ID,Acquired,Original Shares,Shares,Original Basis,Basis,Currency\n"
        b"ACME,LIMIT-A,2020-02-03,1,1,50,50,USD\n"
        b"ACME,LIMIT-B,2021-04-05,1,1,50,50,USD\n"
    )
    staged = _upload(client, account_id, content, key="stage3-safe-batch-001")
    review = client.get(f"/v1/tax-lot-imports/{staged.json()['id']}").json()
    monkeypatch.setenv("TAX_LOT_PUBLICATION_MAX_ROWS", "1")
    response = client.post(
        f"/v1/tax-lot-imports/{review['id']}/publish",
        json={
            "expected_revision": review["review_revision"],
            "acknowledge_quantity_differences": False,
            "reason": "Respect configured safe write batch",
        },
    )
    assert response.status_code == 422
    assert "configured safe publication limit" in response.json()["detail"]
    assert client.get("/v1/tax-lots", params={"account_id": account_id}).json() == []
