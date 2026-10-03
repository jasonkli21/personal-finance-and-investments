"""Regressions for catalog, valuation, ingestion, and local worker review fixes."""

from __future__ import annotations

import io
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zipfile import ZipFile
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session
from test_funds import catalog
from test_funds import client as client
from test_stage2_transactions import stage2_database as stage2_database

from app.db.models import (
    Account,
    FinancialTransaction,
    IssuerMappingEvent,
    Job,
    PositionSnapshot,
    Quote,
    TransactionImport,
    utc_now,
)
from app.domains import jobs, portfolio, reports, transactions
from app.domains.imports import InvalidCsv
from app.providers.fund_formats import parse_fund


def _account(browser: TestClient) -> str:
    result = browser.post(
        "/v1/accounts",
        json={
            "name": "Synthetic review",
            "account_type": "checking",
            "base_currency": "USD",
        },
    )
    assert result.status_code == 201, result.text
    return str(result.json()["id"])


def _transaction_upload(
    browser: TestClient,
    account_id: str,
    content: bytes,
    *,
    key: str = "synthetic-review",
    mapping: dict[str, str] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    return browser.post(
        "/v1/imports/transactions/preview",
        content=content,
        headers={
            "Content-Type": "text/csv",
            "X-Account-Id": account_id,
            "X-Source-Label": "Synthetic bank",
            "X-Column-Mapping": json.dumps(
                mapping
                or {
                    "posted_date": "posted",
                    "amount": "amount",
                    "description": "description",
                }
            ),
            "X-File-Name": "synthetic.csv",
            "Idempotency-Key": key,
            **(extra_headers or {}),
        },
    )


def test_catalog_creation_with_issuer_preserves_mapping_audit(client: Any) -> None:
    browser, engine = client
    issuer = browser.post("/v1/issuers", json={"display_name": "Synthetic Issuer"})
    assert issuer.status_code == 201
    created = browser.post(
        "/v1/securities",
        json={
            "security_type": "equity",
            "display_ticker": "REVIEW",
            "name": "Synthetic Reviewed Security",
            "currency": "USD",
            "issuer_id": issuer.json()["id"],
        },
    )
    assert created.status_code == 201, created.text
    with Session(engine) as session:
        audit = session.scalar(
            select(IssuerMappingEvent).where(
                IssuerMappingEvent.security_id == UUID(created.json()["id"])
            )
        )
        assert audit is not None
        assert audit.previous_issuer_id is None
        assert audit.new_issuer_id == UUID(issuer.json()["id"])


def test_unresolved_position_can_be_explicitly_excluded_without_losing_source(
    client: Any,
) -> None:
    browser, _engine = client
    security_id = catalog(browser, "KNOWN", "equity")
    account_id = _account(browser)
    preview = browser.post(
        "/v1/imports/positions/preview",
        content=b"ticker,quantity,price\nKNOWN,2,10\nUNRESOLVED,7,3\n",
        headers={
            "Content-Type": "text/csv",
            "X-Account-Id": account_id,
            "X-Effective-Date": "2026-10-01",
            "X-Expected-Account-Revision": "0",
            "X-Source-Label": "Synthetic positions",
            "X-Column-Mapping": json.dumps(
                {"identifier": "ticker", "quantity": "quantity", "price": "price"}
            ),
            "Idempotency-Key": "exclude-unresolved-source",
        },
    )
    assert preview.status_code == 200, preview.text
    import_id = preview.json()["id"]
    row = browser.get(f"/v1/imports/{import_id}").json()["rows"][1]
    correction = browser.patch(
        f"/v1/imports/{import_id}/rows/{row['id']}",
        json={
            "expected_review_revision": 1,
            "excluded": True,
            "reason": "Reviewed irrelevant source row",
        },
    )
    assert correction.status_code == 200, correction.text
    published = browser.post(
        f"/v1/imports/{import_id}/publish", json={"expected_review_revision": 2}
    )
    assert published.status_code == 200, published.text
    assert [line["security"]["id"] for line in published.json()["positions"]] == [
        security_id
    ]
    retained = browser.get(f"/v1/imports/{import_id}").json()["rows"][1]
    assert retained["excluded"] and retained["security_id"] is None
    assert retained["raw_payload"]["ticker"] == "UNRESOLVED"


def test_owned_and_report_valuations_share_current_quote_policy(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, engine = client
    now = datetime(2026, 10, 2, 12, tzinfo=UTC)
    monkeypatch.setattr(portfolio, "utc_now", lambda: now)
    monkeypatch.setattr(reports, "utc_now", lambda: now)
    account_id = _account(browser)
    security_id = catalog(browser, "VALUED", "equity")
    saved = browser.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": "2026-09-01",
            "positions": [
                {
                    "security_id": security_id,
                    "quantity": "2",
                    "reported_price": "5",
                    "currency": "USD",
                }
            ],
        },
    )
    assert saved.status_code == 200
    stale = browser.get(f"/v1/portfolio/owned/{account_id}").json()
    frozen_stale = browser.post("/v1/portfolio/reports", json={}).json()
    assert stale["completeness"] == "incomplete"
    assert stale["lines"][0]["quality_status"] == "stale"
    assert frozen_stale["nav_status"] == "incomplete"
    assert any("stale value" in warning for warning in frozen_stale["warnings"])
    with Session(engine) as session:
        for price, quality, observed in [
            ("7", "reported", datetime(2026, 10, 1, 12, tzinfo=UTC)),
            ("999", "rejected", datetime(2026, 10, 2, 10, tzinfo=UTC)),
            ("888", "reported", datetime(2026, 10, 3, 12, tzinfo=UTC)),
        ]:
            session.add(
                Quote(
                    id=uuid4(),
                    security_id=UUID(security_id),
                    as_of=observed,
                    price=Decimal(price),
                    currency="USD",
                    source=f"synthetic-{quality}-{price}",
                    quality_status=quality,
                    fetched_at=now,
                    provider_metadata={},
                )
            )
        session.commit()
    valued = browser.get(f"/v1/portfolio/owned/{account_id}").json()
    frozen = browser.post("/v1/portfolio/reports", json={}).json()
    assert Decimal(valued["total_usd"]) == Decimal(frozen["total_portfolio_nav"]) == 14
    historical = browser.get(
        f"/v1/portfolio/owned/{account_id}", params={"as_of": "2026-09-01"}
    ).json()
    assert Decimal(historical["total_usd"]) == 10


def test_position_effective_date_uses_utc_when_connection_timezone_differs() -> None:
    snapshot = PositionSnapshot(
        id=uuid4(),
        account_id=uuid4(),
        snapshot_at=datetime(2026, 10, 1, tzinfo=UTC).astimezone(
            ZoneInfo("America/Los_Angeles")
        ),
        source="synthetic",
        revision=1,
    )
    result = portfolio._as_read(snapshot, [])
    assert result.effective_date == date(2026, 10, 1)


@pytest.mark.parametrize(
    "content",
    [
        b"posted,amount,amount,description\n2026-10-01,-10,-999,Synthetic\n",
        b'posted,amount,description\n2026-10-01,-10,"unterminated\n',
        b"posted,amount,description\n2026-10-01,-10,Synthetic\x00\n",
        b"posted,amount,description,provider\n2026-10-01,-10,Synthetic,"
        + b"x" * 201
        + b"\n",
    ],
)
def test_malformed_transaction_csv_is_rejected_without_review_rows(
    client: Any, content: bytes
) -> None:
    browser, _engine = client
    mapping = {
        "posted_date": "posted",
        "amount": "amount",
        "description": "description",
    }
    if b",provider\n" in content:
        mapping["provider_id"] = "provider"
    result = _transaction_upload(browser, _account(browser), content, mapping=mapping)
    assert result.status_code == 422, result.text
    assert browser.get("/v1/transactions").json() == []


def test_transaction_import_identity_includes_mapping_and_statement_dates(
    client: Any,
) -> None:
    browser, _engine = client
    account_id = _account(browser)
    content = b"posted,amount,alternate,description\n2026-10-01,-10,-20,Synthetic\n"
    first = _transaction_upload(browser, account_id, content)
    assert first.status_code == 201
    repeated = _transaction_upload(browser, account_id, content)
    assert repeated.json()["id"] == first.json()["id"] and repeated.json()["duplicate"]
    changed = {
        "posted_date": "posted",
        "amount": "alternate",
        "description": "description",
    }
    for key in ("synthetic-review", "different-key"):
        result = _transaction_upload(
            browser, account_id, content, key=key, mapping=changed
        )
        assert result.status_code == 409, result.text
    dated = _transaction_upload(
        browser,
        account_id,
        content,
        extra_headers={"X-Statement-Start": "2026-10-01"},
    )
    assert dated.status_code == 409, dated.text


def test_transaction_write_budget_accounts_for_serialized_unicode_expansion(
    client: Any,
) -> None:
    browser, engine = client
    account_id = _account(browser)
    # Each UTF-8 character occupies two bytes in the CSV and six bytes in the
    # JSON escaping used by the database adapter; every field is otherwise valid.
    headers = ["posted", "amount", "description"] + [f"extra{i}" for i in range(20)]
    row = ["2026-10-01", "-10", "Synthetic"] + ["é" * 2000] * 20
    content = (",".join(headers) + "\n" + (",".join(row) + "\n") * 10).encode()
    assert len(content) < 1_000_000
    result = _transaction_upload(browser, account_id, content)
    assert result.status_code == 422, result.text
    assert "2 MB write budget" in result.json()["detail"]
    with Session(engine) as session:
        assert session.scalar(select(TransactionImport.id)) is None
        assert session.scalar(select(FinancialTransaction.id)) is None


def test_transaction_retry_rechecks_provider_identity_from_pristine_input(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, _engine = client
    account_id = _account(browser)
    mapping = {
        "posted_date": "posted",
        "transaction_date": "occurred",
        "amount": "amount",
        "description": "description",
        "provider_id": "provider",
    }
    first = _transaction_upload(
        browser,
        account_id,
        b"posted,occurred,amount,description,provider\n"
        b"2026-10-01,2026-09-29,-10,Synthetic,native-id\n",
        key="native-first",
        mapping=mapping,
    )
    assert first.status_code == 201, first.text
    published = browser.post(
        f"/v1/transaction-imports/{first.json()['id']}/publish",
        json={"expected_review_revision": 1, "reason": "Synthetic acceptance"},
    )
    assert published.status_code == 200, published.text
    canonical_id = UUID(browser.get("/v1/transactions").json()[0]["id"])

    class AbortedAttempt(Exception):
        pass

    def retry_after_concurrent_change(factory: Any, operation: Any) -> Any:
        # Exercise real rollback/persistence while simulating the retry seam.
        # The first attempt sees a duplicate; the next sees changed source data.
        with pytest.raises(AbortedAttempt), factory.begin() as session:
            operation(session)
            raise AbortedAttempt
        with factory.begin() as session:
            session.execute(
                update(FinancialTransaction)
                .where(FinancialTransaction.id == canonical_id)
                .values(transaction_date=date(2026, 9, 30))
            )
        with factory.begin() as session:
            return operation(session)

    monkeypatch.setattr(
        transactions, "run_database_unit", retry_after_concurrent_change
    )
    retried = _transaction_upload(
        browser,
        account_id,
        b"posted,occurred,amount,description,provider,note\n"
        b"2026-10-01,2026-09-29,-10,Synthetic,native-id,Another export\n",
        key="native-retried",
        mapping=mapping,
    )
    assert retried.status_code == 201, retried.text
    review = browser.get(f"/v1/transaction-imports/{retried.json()['id']}").json()[
        "rows"
    ][0]
    assert review["status"] == "needs_review"
    assert review["diagnostics"]["native_id_conflict"] == str(canonical_id)


def test_expired_job_cannot_renew_or_complete_and_can_be_cancelled(
    stage2_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser, _engine = stage2_database
    factory = browser.app.state.session_factory
    now = utc_now()
    monkeypatch.setattr(jobs, "utc_now", lambda: now)
    job_id = uuid4()
    with factory.begin() as session:
        session.add(
            Job(
                id=job_id,
                job_type=jobs.PDF_PREVIEW_JOB,
                idempotency_key=str(job_id),
                payload={},
                status="running",
                attempts=1,
                max_attempts=3,
                run_after=now,
                lease_owner="synthetic-worker",
                lease_until=now + timedelta(days=1),
                lease_generation=2,
                cancel_requested=False,
                progress_stage="processing",
                progress_current=0,
                created_at=now,
                updated_at=now,
            )
        )
    # Advance the lease clock without exposing a reclaimable job to the local
    # runner installed by the common app fixture.
    monkeypatch.setattr(jobs, "utc_now", lambda: now + timedelta(days=2))
    claim = jobs.JobClaim(
        job_id, jobs.PDF_PREVIEW_JOB, None, None, {}, "synthetic-worker", 2, 1, 3
    )
    assert jobs.job_cancelled_or_stale(factory, claim) == (False, True)
    assert not jobs.progress_job(
        factory, claim, stage="expired", current=1, total=1, lease_seconds=30
    )
    assert not jobs.complete_job(factory, claim, {"synthetic": True})
    cancelled = browser.post(f"/v1/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    with factory() as session:
        row = session.get(Job, job_id)
        assert row is not None and row.lease_owner is None and row.lease_generation == 3


def test_transaction_listing_batches_related_reads(client: Any) -> None:
    browser, engine = client
    account_id = _account(browser)
    for index in range(12):
        result = browser.post(
            "/v1/transactions/manual",
            json={
                "account_id": account_id,
                "posted_date": "2026-10-01",
                "amount": "-12.50",
                "currency": "USD",
                "description": f"Synthetic purchase {index}",
                "idempotency_key": f"batch-query-{index}",
            },
        )
        assert result.status_code == 201, result.text
    statements: list[str] = []

    def record_query(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _many: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_query)
    try:
        with Session(engine) as session:
            result = transactions.list_transactions(
                session,
                account_id=UUID(account_id),
                start_date=None,
                end_date=None,
                limit=100,
            )
    finally:
        event.remove(engine, "before_cursor_execute", record_query)
    assert len(result) == 12 and all(row["split_count"] == 0 for row in result)
    assert len(statements) <= 4


def test_finance_summary_rejects_silent_account_truncation(client: Any) -> None:
    browser, engine = client
    with Session(engine) as session:
        session.add_all(
            [
                Account(
                    id=uuid4(),
                    name=f"Synthetic {index}",
                    account_type="checking",
                    base_currency="USD",
                    active=True,
                    source_type="manual",
                )
                for index in range(501)
            ]
        )
        session.commit()
    result = browser.get("/v1/finance/summary", params={"month": "2026-10-01"})
    assert result.status_code == 422, result.text
    assert "500 accounts" in result.json()["detail"]


def test_fund_parser_bounds_blank_records_and_rejects_missing_inline_string() -> None:
    with pytest.raises(InvalidCsv, match="row limit"):
        parse_fund(
            b"ticker,weight\n" + b"\n" * 1000,
            format_id="manual",
            ticker="SYNTHETIC",
            as_of=date(2026, 10, 1),
            mapping={"identifier": "ticker", "weight": "weight"},
            weight_unit="percent",
            max_rows=1,
        )
    data = io.BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
            '2006/main"><sheetData><row><c r="A1" t="inlineStr" />'
            "</row></sheetData></worksheet>",
        )
    with pytest.raises(InvalidCsv, match="inline string is missing"):
        parse_fund(
            data.getvalue(),
            format_id="spdr",
            ticker="SPY",
            as_of=date(2026, 10, 1),
            mapping={},
            weight_unit="percent",
            max_rows=10,
        )
