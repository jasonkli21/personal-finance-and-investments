"""Frozen reports reconcile exact synthetic portfolios on SQLite and actual PG16."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_funds import catalog, upload
from test_funds import client as client

from app.db.models import Calculation
from app.domains import reports
from app.main import create_app


def account(browser: TestClient, name: str) -> str:
    response = browser.post(
        "/v1/accounts",
        json={"name": name, "account_type": "taxable", "base_currency": "USD"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def positions(
    browser: TestClient,
    identifier: str,
    rows: list[tuple[str, str, str | None, str]],
    revision: int = 0,
    date: str = "2026-10-01",
) -> None:
    response = browser.put(
        f"/v1/accounts/{identifier}/positions",
        json={
            "expected_revision": revision,
            "effective_date": date,
            "positions": [
                {"security_id": s, "quantity": q, "reported_price": p, "currency": c}
                for s, q, p, c in rows
            ],
        },
    )
    assert response.status_code == 200, response.text


def accept(browser: TestClient, fund: str, content: bytes) -> None:
    result = upload(browser, fund, content)
    response = browser.post(
        f"/v1/fund-imports/{result['id']}/publish", json={"expected_review_revision": 1}
    )
    assert response.status_code == 200, response.text


def report(browser: TestClient, **kwargs: Any) -> dict[str, Any]:
    response = browser.post("/v1/portfolio/reports", json=kwargs)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_golden_filters_export_freeze_restart_and_integrity(
    client: Any, monkeypatch: Any
) -> None:
    browser, engine = client
    monkeypatch.setattr(
        reports, "utc_now", lambda: datetime(2026, 10, 2, 12, tzinfo=UTC)
    )
    nvda = catalog(browser, "NVDA", "equity")
    other = catalog(browser, "OTHER", "equity")
    fa = catalog(browser, "FA")
    fb = catalog(browser, "FB")
    a = account(browser, "Brokerage")
    b = account(browser, "Retirement")
    positions(
        browser,
        a,
        [
            (nvda, "300", "100", "USD"),
            (fa, "500", "100", "USD"),
            (other, "1000", "100", "USD"),
        ],
    )
    positions(browser, b, [(fb, "200", "100", "USD")])
    accept(browser, fa, b"ticker,weight,type\nNVDA,8,equity\nOTHER,92,equity\n")
    accept(browser, fb, b"ticker,weight,type\nNVDA,6,equity\nOTHER,94,equity\n")
    frozen = report(browser)
    identifier = frozen["id"]
    assert Decimal(frozen["total_portfolio_nav"]) == 200000
    issuer_csv = browser.get(
        f"/v1/portfolio/reports/{identifier}/export", params={"view": "issuer"}
    )
    assert (
        sum(Decimal(r["value"]) for r in csv.DictReader(io.StringIO(issuer_csv.text)))
        == 200000
    )
    assert Decimal(frozen["issuer_unmapped_value"]) == 200000
    assert frozen["reconciled"] and Decimal(frozen["security_coverage"]) == 100
    row = browser.get(
        f"/v1/portfolio/reports/{identifier}/rows", params={"q": "NVDA"}
    ).json()["rows"][0]
    assert (
        Decimal(row["direct"]),
        Decimal(row["indirect"]),
        Decimal(row["total"]),
        Decimal(row["percentage"]),
    ) == (Decimal("30000"), Decimal("5200"), Decimal("35200"), Decimal("17.6"))
    contributions = browser.get(
        f"/v1/portfolio/reports/{identifier}/breakdown/{nvda}"
    ).json()
    assert sum((Decimal(c["amount"]) for c in contributions), Decimal(0)) == 35200
    assert len(contributions) == 3 and all(
        c["position_snapshot_id"] for c in contributions
    )
    export = browser.get(
        f"/v1/portfolio/reports/{identifier}/export", params={"q": "NVDA"}
    )
    exported = list(csv.DictReader(io.StringIO(export.text)))
    assert (
        Decimal(exported[0]["value"]) == 35200
        and exported[0]["calculation_id"] == identifier
    )
    assert Decimal(exported[0]["percentage_of_total_portfolio"]) == Decimal("17.6")
    assert Decimal(report(browser, account_ids=[a])["total_portfolio_nav"]) == 180000
    # A new accepted price/position/fund changes a new report, never the artifact.
    positions(browser, a, [(nvda, "400", "100", "USD")], revision=1)
    accept(browser, fa, b"ticker,weight,type\nNVDA,20,equity\nOTHER,80,equity\n")
    assert Decimal(report(browser)["total_portfolio_nav"]) == 60000
    assert browser.get(f"/v1/portfolio/reports/{identifier}").json() == frozen
    # Reconstruct the application; report metadata + private artifact are sufficient.
    restarted = TestClient(create_app(engine=engine))
    assert (
        restarted.get(
            f"/v1/portfolio/reports/{identifier}/export", params={"q": "NVDA"}
        ).text
        == export.text
    )
    with browser.app.state.session_factory() as session:
        metadata = session.scalar(
            select(Calculation).where(
                Calculation.id == __import__("uuid").UUID(identifier)
            )
        )
        assert metadata is not None
        artifact = Path(browser.app.state.private_file_root) / metadata.storage_key
        artifact.write_bytes(b"corrupted")
    assert browser.get(f"/v1/portfolio/reports/{identifier}").status_code == 404


def test_partial_opaque_missing_currency_signed_and_historical(
    client: Any, monkeypatch: Any
) -> None:
    browser, _ = client
    monkeypatch.setattr(
        reports, "utc_now", lambda: datetime(2026, 10, 2, 12, tzinfo=UTC)
    )
    equity = catalog(browser, "EQ", "equity")
    fund = catalog(browser, "FUND")
    foreign = browser.post(
        "/v1/securities",
        json={
            "security_type": "equity",
            "display_ticker": "FOREIGN",
            "name": "Synthetic EUR",
            "currency": "EUR",
        },
    ).json()["id"]
    a = account(browser, "Partial")
    positions(browser, a, [(fund, "100", "100", "USD")])
    accept(browser, fund, b"ticker,weight,type\nEQ,92,equity\nUSD,5,cash\n")
    partial = report(browser)
    assert Decimal(partial["security_coverage"]) == 92
    assert {k: Decimal(v) for k, v in partial["categories"].items()} == {
        "indirect": Decimal(9200),
        "cash": Decimal(500),
        "missing_weight": Decimal(300),
    }
    accept(browser, fund, b"ticker,weight,type\nEQ,105,equity\n")
    opaque = report(browser)
    assert Decimal(opaque["categories"]["opaque_fund"]) == 10000
    assert Decimal(opaque["security_coverage"]) == 0
    positions(
        browser,
        a,
        [(equity, "1", None, "USD"), (foreign, "2", "10", "EUR")],
        revision=1,
        date="2026-10-02",
    )
    incomplete = report(browser)
    assert (
        incomplete["nav_status"] == "incomplete"
        and incomplete["total_portfolio_nav"] is None
    )
    assert not incomplete["percentages_available"]
    owned = browser.get(
        f"/v1/portfolio/reports/{incomplete['id']}/rows", params={"view": "owned"}
    ).json()["rows"]
    assert {r["status"] for r in owned} == {"unpriced", "foreign_currency"}
    historical = report(browser, as_of="2026-10-01T12:00:00Z")
    assert Decimal(historical["total_portfolio_nav"]) == 10000
    positions(browser, a, [(equity, "-2", "10", "USD")], revision=2)
    signed = report(browser)
    assert (
        Decimal(signed["total_portfolio_nav"]) == -20
        and signed["security_coverage"] is None
    )
    assert signed["reconciled"]
    positions(browser, a, [], revision=3)
    zero = report(browser)
    assert (
        Decimal(zero["included_valued_nav"]) == 0 and not zero["percentages_available"]
    )
    assert (
        browser.post(
            "/v1/portfolio/reports", json={"as_of": "2027-01-01T00:00:00Z"}
        ).status_code
        == 422
    )
    assert (
        browser.post(
            "/v1/portfolio/reports", json={"as_of": "2026-10-01T00:00:00"}
        ).status_code
        == 422
    )


def test_issuer_mapping_quote_priority_and_frozen_provenance(
    client: Any, monkeypatch: Any
) -> None:
    from uuid import UUID, uuid4

    from app.db.models import Quote

    browser, engine = client
    monkeypatch.setattr(
        reports, "utc_now", lambda: datetime(2026, 10, 2, 12, tzinfo=UTC)
    )
    issuer = browser.post(
        "/v1/issuers", json={"display_name": "Synthetic Alphabet"}
    ).json()["id"]
    goog = catalog(browser, "GOOG", "equity")
    googl = catalog(browser, "GOOGL", "equity")
    for s in [goog, googl]:
        response = browser.patch(
            f"/v1/securities/{s}/issuer",
            json={
                "issuer_id": issuer,
                "expected_issuer_id": None,
                "reason": "Reviewed synthetic share classes",
            },
        )
        assert response.status_code == 200, response.text
    a = account(browser, "Share classes")
    positions(browser, a, [(goog, "2", "5", "USD"), (googl, "1", "10", "USD")])
    for source, price, currency, quality, time in [
        ("preferred", "7", "USD", "reported", "2026-10-01T12:00:00+00:00"),
        ("other", "99", "USD", "reported", "2026-10-01T12:00:00+00:00"),
        ("preferred", "999", "EUR", "reported", "2026-10-02T00:00:00+00:00"),
        ("rejected-provider", "999", "USD", "rejected", "2026-10-02T00:00:00+00:00"),
        ("preferred", "999", "USD", "reported", "2026-10-03T00:00:00+00:00"),
    ]:
        with browser.app.state.session_factory.begin() as session:
            session.add(
                Quote(
                    id=uuid4(),
                    security_id=UUID(goog),
                    as_of=datetime.fromisoformat(time),
                    price=Decimal(price),
                    currency=currency,
                    source=source,
                    fetched_at=datetime(2026, 10, 2, tzinfo=UTC),
                    quality_status=quality,
                    provider_metadata={},
                )
            )
    monkeypatch.setenv("QUOTE_SOURCE_PRIORITY", "preferred,other")
    frozen = report(browser)
    assert Decimal(frozen["included_valued_nav"]) == 24
    assert Decimal(frozen["issuer_coverage"]) == 100
    rows = browser.get(
        f"/v1/portfolio/reports/{frozen['id']}/rows", params={"view": "issuer"}
    ).json()["rows"]
    assert len(rows) == 1 and Decimal(rows[0]["total"]) == 24
    response = browser.post(
        "/v1/market-data/quotes",
        json={
            "security_id": goog,
            "price": "8",
            "currency": "USD",
            "as_of": "2026-10-01T12:00:00Z",
            "reason": "Reviewed override",
        },
    )
    assert response.status_code == 201
    assert Decimal(report(browser)["included_valued_nav"]) == 26
    response = browser.patch(
        f"/v1/securities/{goog}/issuer",
        json={
            "issuer_id": None,
            "expected_issuer_id": issuer,
            "reason": "Remove reviewed mapping",
        },
    )
    assert response.status_code == 200
    detail = browser.get(
        f"/v1/portfolio/reports/{frozen['id']}/breakdown/{issuer}",
        params={"level": "issuer"},
    ).json()
    assert len(detail) == 2 and sum(Decimal(c["amount"]) for c in detail) == 24
    assert browser.get(f"/v1/portfolio/reports/{frozen['id']}").json() == frozen


def test_formula_safe_csv_keeps_signed_numeric_values(
    client: Any, monkeypatch: Any
) -> None:
    browser, _ = client
    monkeypatch.setattr(
        reports, "utc_now", lambda: datetime(2026, 10, 2, 12, tzinfo=UTC)
    )
    security = catalog(browser, "=1+1", "equity")
    a = account(browser, "@danger")
    positions(browser, a, [(security, "-1", "10", "USD")])
    frozen = report(browser)
    csv_text = browser.get(f"/v1/portfolio/reports/{frozen['id']}/export").text
    row = list(csv.DictReader(io.StringIO(csv_text)))[0]
    assert row["label"] == "'=1+1" and row["accounts"] == "'@danger"
    assert Decimal(row["value"]) == -10 and not row["value"].startswith("'")


def test_concurrent_import_publication_and_old_duplicate_do_not_move_head(
    client: Any,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID, uuid4

    import pytest

    from app.domains import imports

    browser, engine = client
    if engine.dialect.name == "sqlite":
        pytest.skip("Concurrent publication requires PostgreSQL")
    s = catalog(browser, "CONCURRENT", "equity")
    a = account(browser, "Concurrent")
    attempts = []
    for quantity in [1, 2]:
        response = browser.post(
            "/v1/imports/positions/preview",
            content=f"ticker,quantity,price,currency\nCONCURRENT,{quantity},10,USD\n".encode(),
            headers={
                "Content-Type": "text/csv",
                "X-Account-Id": a,
                "X-Effective-Date": "2026-10-01",
                "X-Expected-Account-Revision": "0",
                "X-Source-Label": "Concurrency fixture",
                "X-Column-Mapping": (
                    '{"identifier":"ticker","quantity":"quantity",'
                    '"price":"price","currency":"currency"}'
                ),
                "Idempotency-Key": str(uuid4()),
            },
        )
        assert response.status_code == 200, response.text
        attempts.append(response.json()["id"])
    barrier = Barrier(2)

    def commit(identifier: str) -> str:
        barrier.wait(timeout=10)
        try:
            imports.publish_position_import(
                browser.app.state.session_factory,
                UUID(identifier),
                expected_review_revision=1,
            )
            return identifier
        except (imports.ImportAccountConflict, imports.ImportRevisionConflict):
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(commit, attempts))
    assert result.count("conflict") == 1
    winner = next(r for r in result if r != "conflict")
    current = browser.get(f"/v1/accounts/{a}/positions").json()
    assert current["current_revision"] == 1
    positions(browser, a, [(s, "5", "10", "USD")], revision=1)
    repeated = browser.post(
        f"/v1/imports/{winner}/publish", json={"expected_review_revision": 1}
    )
    assert repeated.status_code == 200, repeated.text
    assert browser.get(f"/v1/accounts/{a}/positions").json()["current_revision"] == 2
    assert (
        browser.get(f"/v1/accounts/{a}/positions")
        .json()["snapshot"]["positions"][0]["quantity"]
        .startswith("5")
    )
