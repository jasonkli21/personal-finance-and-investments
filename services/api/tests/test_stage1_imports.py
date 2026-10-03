"""Offline review, private staging, and publication tests for Stage 1.1."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, ImportBatch, ImportRow, PrivateFile, Quote, Security
from app.main import create_app
from app.storage.file_store import PrivateFileStore


@pytest.fixture
def stage1_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, UUID, Engine]]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("MAX_IMPORT_FILE_BYTES", "5000000")
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
                name="Acme Synthetic Corp.",
                currency="USD",
            )
        )
        session.commit()
    app = create_app(engine=engine)
    with TestClient(app) as client:
        yield client, security_id, engine
    engine.dispose()


def _account(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/v1/accounts",
        json={
            "name": "Import test account",
            "account_type": "taxable",
            "base_currency": "USD",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def _upload(
    client: TestClient,
    *,
    account_id: str,
    revision: int,
    effective_date: str,
    content: bytes,
    key: str,
    mapping: dict[str, str] | None = None,
) -> Any:
    return client.post(
        "/v1/imports/positions/preview",
        content=content,
        headers={
            "Content-Type": "text/csv",
            "X-Account-Id": account_id,
            "X-Effective-Date": effective_date,
            "X-Expected-Account-Revision": str(revision),
            "X-Source-Label": "Synthetic statement export",
            "X-Column-Mapping": json.dumps(
                mapping
                or {
                    "identifier": "Symbol",
                    "quantity": "Shares",
                    "price": "Price",
                    "currency": "Currency",
                    "asset_type": "Type",
                }
            ),
            "X-File-Name": "synthetic-positions.csv",
            "Idempotency-Key": key,
        },
    )


def test_private_store_is_content_addressed_and_owner_only(tmp_path: Path) -> None:
    store = PrivateFileStore(tmp_path / "private")
    key, digest = store.put(b"synthetic,private,csv\n")
    repeated_key, repeated_digest = store.put(b"synthetic,private,csv\n")
    path = tmp_path / "private" / key
    assert key == repeated_key
    assert digest == repeated_digest
    assert store.read(key) == b"synthetic,private,csv\n"
    assert os.stat(tmp_path / "private").st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="Invalid private file key"):
        store.read("../private.csv")


def test_review_correct_publish_and_historical_value_are_offline(
    stage1_context: tuple[TestClient, UUID, Engine],
) -> None:
    client, _known_security_id, _engine = stage1_context
    account = _account(client)
    account_id = account["id"]
    manual = client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": "2026-09-29",
            "positions": [
                {
                    "security_id": str(_known_security_id),
                    "quantity": "1",
                    "reported_price": "9",
                    "currency": "USD",
                }
            ],
        },
    )
    assert manual.status_code == 200

    csv_data = (
        b"Symbol,Shares,Price,Currency,Type\n"
        b"ACME,2,10,USD,equity\n"
        b"NEWCO,3,2,USD,equity\n"
    )
    preview = _upload(
        client,
        account_id=account_id,
        revision=1,
        effective_date="2026-09-30",
        content=csv_data,
        key="position-import-review-1",
    )
    assert preview.status_code == 200
    preview_data = preview.json()
    import_id = preview_data["id"]
    assert preview_data["status"] == "review"
    assert preview_data["row_count"] == 2
    assert preview_data["batch_count"] == 1
    review = client.get(f"/v1/imports/{import_id}").json()
    assert [row["row_status"] for row in review["rows"]] == ["ready", "unmatched"]
    assert review["rows"][1]["raw_payload"]["Symbol"] == "NEWCO"

    blocked = client.post(
        f"/v1/imports/{import_id}/publish",
        json={"expected_review_revision": 1, "reason": "test"},
    )
    assert blocked.status_code == 422

    created_security = client.post(
        "/v1/securities",
        json={
            "security_type": "equity",
            "display_ticker": "NEWCO",
            "name": "Newco Synthetic Inc.",
            "currency": "USD",
        },
    )
    assert created_security.status_code == 201
    row = review["rows"][1]
    correction = client.patch(
        f"/v1/imports/{import_id}/rows/{row['id']}",
        json={
            "expected_review_revision": 1,
            "reason": "Matched to manually authored catalog record",
            "security_id": created_security.json()["id"],
            "quantity": "3",
            "price": "2",
            "currency": "USD",
        },
    )
    assert correction.status_code == 200
    assert correction.json()["row_status"] == "ready"
    stale_correction = client.patch(
        f"/v1/imports/{import_id}/rows/{row['id']}",
        json={
            "expected_review_revision": 1,
            "reason": "stale client draft",
            "quantity": "4",
        },
    )
    assert stale_correction.status_code == 409

    published = client.post(
        f"/v1/imports/{import_id}/publish",
        json={"expected_review_revision": 2, "reason": "review complete"},
    )
    assert published.status_code == 200
    assert published.json()["effective_date"] == "2026-09-30"
    assert len(published.json()["positions"]) == 2
    current = client.get(f"/v1/accounts/{account_id}/positions").json()
    assert current["current_revision"] == 2
    assert current["snapshot"]["id"] == published.json()["id"]
    owned = client.get(f"/v1/portfolio/owned/{account_id}").json()
    assert owned["total_usd"] == "26.0000000000"
    assert owned["percentages_available"] is True
    assert sum(
        Decimal(line["allocation_percent"]) for line in owned["lines"]
    ) == Decimal("100.0000000000")

    historic = client.get(
        f"/v1/accounts/{account_id}/positions", params={"as_of": "2026-09-29"}
    ).json()
    assert historic["snapshot"]["revision"] == 1
    historic_value = client.get(
        f"/v1/portfolio/owned/{account_id}", params={"as_of": "2026-09-29"}
    ).json()
    assert historic_value["total_usd"] == "9.0000000000"

    repeated = _upload(
        client,
        account_id=account_id,
        revision=1,
        effective_date="2026-09-30",
        content=csv_data,
        key="position-import-review-duplicate",
    )
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["id"] == import_id
    assert (
        client.get(f"/v1/accounts/{account_id}/positions").json()["current_revision"]
        == 2
    )

    changed_payload = _upload(
        client,
        account_id=account_id,
        revision=1,
        effective_date="2026-09-30",
        content=csv_data.replace(b"ACME,2,10", b"ACME,7,10"),
        key="position-import-review-1",
    )
    assert changed_payload.status_code == 409

    private_files = client.get("/openapi.json")
    assert private_files.status_code == 200


def test_import_batches_are_row_and_byte_bounded_and_cancelled_work_cannot_publish(
    stage1_context: tuple[TestClient, UUID, Engine],
) -> None:
    client, _security_id, engine = stage1_context
    account = _account(client)
    content = (
        "Symbol,Shares,Price,Currency,Type\n" + "ACME,1,1,USD,equity\n" * 201
    ).encode()
    preview = _upload(
        client,
        account_id=account["id"],
        revision=0,
        effective_date="2026-10-01",
        content=content,
        key="bounded-import",
    )
    assert preview.status_code == 200
    assert preview.json()["batch_count"] == 2
    import_id = preview.json()["id"]
    # The API response records bounded markers; SQL rows never exceed 200 per batch.
    with Session(engine) as session:
        batch_rows = list(
            session.scalars(
                select(ImportBatch.row_count).where(
                    ImportBatch.import_id == UUID(import_id),
                    ImportBatch.purpose == "preview",
                )
            )
        )
        assert sorted(batch_rows) == [1, 200]
        assert (
            session.scalar(
                select(ImportRow.id).where(
                    ImportRow.import_id == UUID(import_id), ImportRow.row_number == 202
                )
            )
            is not None
        )
        file_count = len(list(session.scalars(select(PrivateFile.id))))
        assert file_count == 1

    cancelled = client.post(
        f"/v1/imports/{import_id}/cancel",
        json={"expected_review_revision": 1, "reason": "cancelled test batch"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    publish = client.post(
        f"/v1/imports/{import_id}/publish",
        json={"expected_review_revision": 2, "reason": "should not publish"},
    )
    assert publish.status_code == 409


def test_cached_quote_asof_precedence_and_signed_percentages(
    stage1_context: tuple[TestClient, UUID, Engine],
) -> None:
    client, security_id, engine = stage1_context
    account = _account(client)
    saved = client.put(
        f"/v1/accounts/{account['id']}/positions",
        json={
            "expected_revision": 0,
            "effective_date": "2026-09-30",
            "positions": [
                {
                    "security_id": str(security_id),
                    "quantity": "2",
                    "reported_price": None,
                    "currency": "USD",
                }
            ],
        },
    )
    assert saved.status_code == 200
    with Session(engine) as session:
        session.add(
            Quote(
                id=uuid4(),
                security_id=security_id,
                as_of=datetime.fromisoformat("2026-09-29T12:00:00+00:00"),
                price=Decimal("3"),
                currency="USD",
                source="synthetic-provider",
                fetched_at=datetime.fromisoformat("2026-09-29T12:00:00+00:00"),
                quality_status="reported",
                provider_metadata={},
            )
        )
        session.commit()
    reviewed_quote = client.post(
        "/v1/market-data/quotes",
        json={
            "security_id": str(security_id),
            "as_of": "2026-09-29T12:00:00Z",
            "price": "5",
            "currency": "USD",
            "reason": "Synthetic official close check",
        },
    )
    assert reviewed_quote.status_code == 201
    later_quote = client.post(
        "/v1/market-data/quotes",
        json={
            "security_id": str(security_id),
            "as_of": "2026-10-01T12:00:00Z",
            "price": "99",
            "currency": "USD",
            "reason": "Synthetic later observation",
        },
    )
    assert later_quote.status_code == 201
    valued = client.get(f"/v1/portfolio/owned/{account['id']}").json()
    assert valued["total_usd"] == "198.0000000000"
    assert valued["lines"][0]["price"] == "99.0000000000"
    historical = client.get(
        f"/v1/portfolio/owned/{account['id']}", params={"as_of": "2026-09-30"}
    ).json()
    assert historical["total_usd"] == "10.0000000000"
    assert historical["lines"][0]["price"] == "5.0000000000"
    assert valued["lines"][0]["quality_status"] == "reviewed"

    signed_snapshot = client.put(
        f"/v1/accounts/{account['id']}/positions",
        json={
            "expected_revision": 1,
            "effective_date": "2026-10-01",
            "positions": [
                {
                    "security_id": str(security_id),
                    "quantity": "-1",
                    "reported_price": None,
                    "currency": "USD",
                }
            ],
        },
    )
    assert signed_snapshot.status_code == 200
    signed_value = client.get(f"/v1/portfolio/owned/{account['id']}").json()
    assert signed_value["total_usd"] == "-99.0000000000"
    assert signed_value["percentages_available"] is False
    assert signed_value["lines"][0]["allocation_percent"] is None


def test_import_rejects_invalid_currency_precision_and_future_observations(
    stage1_context: tuple[TestClient, UUID, Engine],
) -> None:
    client, _security_id, _engine = stage1_context
    account = _account(client)
    invalid_currency = _upload(
        client,
        account_id=account["id"],
        revision=0,
        effective_date="2026-09-30",
        content=b"Symbol,Shares,Currency\nACME,1,US Dollars\n",
        key="invalid-currency",
        mapping={"identifier": "Symbol", "quantity": "Shares", "currency": "Currency"},
    )
    assert invalid_currency.status_code == 200
    row = client.get(f"/v1/imports/{invalid_currency.json()['id']}").json()["rows"][0]
    assert row["row_status"] == "invalid"
    assert row["raw_currency"] == "US DOLLARS"
    assert row["raw_payload"]["Currency"] == "US Dollars"

    oversized_quantity = _upload(
        client,
        account_id=account["id"],
        revision=0,
        effective_date="2026-09-30",
        content=b"Symbol,Shares\nACME,1000000000000000000\n",
        key="oversized-quantity",
        mapping={"identifier": "Symbol", "quantity": "Shares"},
    )
    assert oversized_quantity.status_code == 200
    row = client.get(f"/v1/imports/{oversized_quantity.json()['id']}").json()["rows"][0]
    assert row["row_status"] == "invalid"
    assert "precision" in row["diagnostics"]["quantity"]

    future = _upload(
        client,
        account_id=account["id"],
        revision=0,
        effective_date="2027-01-01",
        content=b"Symbol,Shares\nACME,1\n",
        key="future-position",
        mapping={"identifier": "Symbol", "quantity": "Shares"},
    )
    assert future.status_code == 422
