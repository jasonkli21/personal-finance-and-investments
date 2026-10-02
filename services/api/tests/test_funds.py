"Synthetic official formats and reviewed bounded publication on both local engines."

from __future__ import annotations

import io
import os
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, FundLine, FundSnapshot, ImportBatch
from app.domains.imports import InvalidCsv
from app.main import create_app
from app.providers.fund_formats import parse_fund


def workbook(rows: list[list[str]]) -> bytes:
    data = io.BytesIO()
    with ZipFile(data, "w") as archive:
        xml = (
            '<worksheet xmlns="http://schemas.openxmlformats.'
            'org/spreadsheetml/2006/main"><sheetData>'
        )
        for i, row in enumerate(rows, 1):
            xml += (
                f'<row r="{i}">'
                + "".join(
                    f'<c r="{chr(65 + j)}{i}" t="inlineStr">'
                    f"<is><t>{escape(v)}</t></is></c>"
                    for j, v in enumerate(row)
                )
                + "</row>"
            )
        archive.writestr("xl/worksheets/sheet1.xml", xml + "</sheetData></worksheet>")
    return data.getvalue()


def test_official_formats_are_dated_not_index_or_top_ten() -> None:
    ivv = (
        b'iShares Core S&P 500 ETF\nFund Holdings as of,"Oc'
        b't 01, 2026"\nTicker,Name,Weight (%),Asset Class,E'
        b"xchange\nNVDA,Synthetic NVIDIA,8,Equity,NASDAQ\nUS"
        b"D,US cash,5,Cash,-\n\nLegal synthetic trailer\n"
    )
    parsed = parse_fund(
        ivv,
        format_id="ishares",
        ticker="IVV",
        as_of=date(2026, 10, 1),
        mapping={},
        weight_unit="percent",
        max_rows=5000,
    )
    assert len(parsed.rows) == 2 and parsed.as_of == date(2026, 10, 1)
    for wrong in [
        ivv.replace(b"Weight (%)", b"Weight changed"),
        ivv.replace(b"Oct 01", b"Sep 30"),
    ]:
        with pytest.raises(InvalidCsv):
            parse_fund(
                wrong,
                format_id="ishares",
                ticker="IVV",
                as_of=date(2026, 10, 1),
                mapping={},
                weight_unit="percent",
                max_rows=5000,
            )
    spy = workbook(
        [
            ["Fund Name:", "State Street SPDR S&P 500 ETF Trust"],
            ["Ticker Symbol:", "SPY"],
            ["Holdings:", "As of 01-Oct-2026"],
            [],
            ["Name", "Ticker", "Identifier", "Weight"],
            ["Synthetic NVIDIA", "NVDA", "SYNTHETIC", "6.123456"],
        ]
    )
    parsed = parse_fund(
        spy,
        format_id="spdr",
        ticker="SPY",
        as_of=date(2026, 10, 1),
        mapping={},
        weight_unit="percent",
        max_rows=5000,
    )
    assert parsed.rows[0]["Weight"] == "6.123456"
    with pytest.raises(InvalidCsv):
        parse_fund(
            spy,
            format_id="spdr",
            ticker="OTHER",
            as_of=date(2026, 10, 1),
            mapping={},
            weight_unit="percent",
            max_rows=5000,
        )


@pytest.fixture(params=["sqlite", "postgres"])
def client(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    if request.param == "postgres":
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            pytest.skip("Disposable PostgreSQL 16 URL not set")
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        # Exercise versioned migrations rather than metadata DDL on PG16.
        from test_core_schema import _migrate

        _migrate(url)
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
    app = create_app(engine=engine)
    with TestClient(app) as browser:
        yield browser, engine
    engine.dispose()


def catalog(client: TestClient, ticker: str, kind: str = "etf") -> str:
    result = client.post(
        "/v1/securities",
        json={
            "security_type": kind,
            "display_ticker": ticker,
            "name": f"Synthetic {ticker}",
            "currency": "USD",
        },
    )
    assert result.status_code == 201, result.text
    return str(result.json()["id"])


def upload(
    client: TestClient,
    fund: str,
    content: bytes,
    key: str | None = None,
    date_value: str = "2026-10-01",
) -> dict[str, Any]:
    result = client.post(
        f"/v1/funds/{fund}/upload",
        content=content,
        headers={
            "X-Effective-Date": date_value,
            "X-Column-Mapping": (
                '{"identifier":"ticker","weight":"weight","asset_type":"type"}'
            ),
            "X-Weight-Unit": "percent",
            "Idempotency-Key": key or str(uuid4()),
        },
    )
    assert result.status_code == 200, result.text
    return result.json()  # type: ignore[no-any-return]


def test_bounded_fund_publication_duplicates_history_and_anomalies(client: Any) -> None:
    browser, engine = client
    fund = catalog(browser, "FA")
    catalog(browser, "NVDA", "equity")
    content = (
        b"ticker,weight,type\nNVDA,8,equity\n"
        + b"\n".join(f"UNKNOWN{i},0,other".encode() for i in range(500))
        + b"\nUSD,5,cash\n"
    )
    attempt = upload(browser, fund, content)
    assert attempt["batch_count"] == 3
    assert browser.get(f"/v1/funds/{fund}/snapshots").json() == []
    published = browser.post(
        f"/v1/fund-imports/{attempt['id']}/publish",
        json={"expected_review_revision": 1},
    )
    assert published.status_code == 200, published.text
    assert published.json()["row_count"] == 502
    assert published.json()["quality_status"] == "partial"
    duplicate = upload(browser, fund, content)
    assert duplicate["id"] == attempt["id"]
    assert (
        browser.post(
            f"/v1/fund-imports/{attempt['id']}/publish",
            json={"expected_review_revision": 1},
        ).json()["id"]
        == published.json()["id"]
    )
    newer = upload(
        browser, fund, b"ticker,weight,type\nNVDA,105,equity\n", date_value="2026-10-02"
    )
    result = browser.post(
        f"/v1/fund-imports/{newer['id']}/publish", json={"expected_review_revision": 1}
    )
    assert result.json()["quality_status"] == "opaque"
    assert len(browser.get(f"/v1/funds/{fund}/snapshots").json()) == 2
    with Session(engine) as session:
        assert len(list(session.scalars(select(FundLine)))) == 503
        assert (
            len(
                list(
                    session.scalars(
                        select(FundSnapshot).where(FundSnapshot.status == "published")
                    )
                )
            )
            == 2
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(ImportBatch).where(ImportBatch.purpose == "fund-publish")
                    )
                )
            )
            == 4
        )


def test_correction_invalidates_approval_cancel_cannot_publish(client: Any) -> None:
    browser, _ = client
    fund = catalog(browser, "FB")
    attempt = upload(browser, fund, b"ticker,weight,type\nUNKNOWN,NaN,exotic\n")
    endpoint = f"/v1/fund-imports/{attempt['id']}/publish"
    assert (
        browser.post(endpoint, json={"expected_review_revision": 1}).status_code == 422
    )
    review = browser.get(f"/v1/imports/{attempt['id']}").json()
    row = review["rows"][0]
    result = browser.patch(
        f"/v1/fund-imports/{attempt['id']}/rows/{row['id']}",
        json={
            "expected_review_revision": 1,
            "weight": "0.1",
            "reason": "Synthetic correction",
            "asset_type": "other",
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["raw_weight_value"] == "NaN"
    assert (
        browser.post(endpoint, json={"expected_review_revision": 1}).status_code == 409
    )
    assert (
        browser.post(
            f"/v1/imports/{attempt['id']}/cancel", json={"expected_review_revision": 2}
        ).status_code
        == 200
    )
    assert (
        browser.post(endpoint, json={"expected_review_revision": 3}).status_code == 409
    )
    assert browser.get(f"/v1/funds/{fund}/snapshots").json() == []
