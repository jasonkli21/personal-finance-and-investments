"""Synthetic Stage 2 transaction review, revision and summary regressions."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.contracts import TransactionPatch
from app.db.models import (
    Base,
    FinancialTransaction,
    ImportAttempt,
    ImportBatch,
    ImportRow,
    Job,
    utc_now,
)
from app.domains import imports, jobs
from app.domains.transactions import TransactionConflict, patch_transaction
from app.main import create_app
from app.storage.file_store import PrivateFileStore


@pytest.fixture(params=["sqlite", "postgres"])
def stage2_database(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    if request.param == "postgres":
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            pytest.skip("set TEST_DATABASE_URL to a disposable PostgreSQL 16 database")
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        from test_core_schema import _migrate

        _migrate(url)
    else:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
    app = create_app(engine=engine)
    with TestClient(app) as browser:
        yield browser, engine
    engine.dispose()


def _account(browser: TestClient) -> dict[str, Any]:
    response = browser.post(
        "/v1/accounts",
        json={
            "name": "Synthetic checking",
            "account_type": "checking",
            "base_currency": "USD",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _manual(
    browser: TestClient,
    account_id: str,
    *,
    amount: str,
    key: str,
    classification: str = "expense",
) -> dict[str, Any]:
    response = browser.post(
        "/v1/transactions/manual",
        json={
            "account_id": account_id,
            "posted_date": "2026-09-15",
            "amount": amount,
            "currency": "USD",
            "description": "Synthetic market purchase",
            "classification": classification,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def _preview(
    browser: TestClient,
    account_id: str,
    *,
    amount: str,
    provider_id: str,
    key: str,
) -> dict[str, Any]:
    response = browser.post(
        "/v1/imports/transactions/preview",
        content=(
            f"posted,amount,description,provider\n"
            f"2026-09-15,{amount},Synthetic Bank Row,{provider_id}\n"
        ).encode(),
        headers={
            "content-type": "text/csv",
            "x-file-name": "synthetic-transactions.csv",
            "x-account-id": account_id,
            "x-source-label": "Synthetic Bank",
            "idempotency-key": key,
            "x-column-mapping": (
                '{"posted_date":"posted","amount":"amount",'
                '"description":"description","provider_id":"provider"}'
            ),
        },
    )
    assert response.status_code == 201, response.text
    return cast(
        dict[str, Any],
        browser.get(f"/v1/transaction-imports/{response.json()['id']}").json(),
    )


def _publish(browser: TestClient, review: dict[str, Any]) -> None:
    response = browser.post(
        f"/v1/transaction-imports/{review['id']}/publish",
        json={
            "expected_review_revision": review["review_revision"],
            "reason": "Synthetic review",
        },
    )
    assert response.status_code == 200, response.text


def test_replacing_existing_splits_reuses_indexes_after_delete(
    stage2_database: Any,
) -> None:
    browser, _engine = stage2_database
    account = _account(browser)
    transaction = _manual(browser, account["id"], amount="-100.00", key="split-parent")
    first = browser.put(
        f"/v1/transactions/{transaction['id']}/splits",
        json={
            "expected_revision": 1,
            "reason": "First split",
            "splits": [{"amount": "-100.00"}],
        },
    )
    assert first.status_code == 200, first.text
    replacement = browser.put(
        f"/v1/transactions/{transaction['id']}/splits",
        json={
            "expected_revision": 2,
            "reason": "Replace allocation",
            "splits": [{"amount": "-60.00"}, {"amount": "-40.00"}],
        },
    )
    assert replacement.status_code == 200, replacement.text
    assert [row["amount"] for row in replacement.json()] == [
        "-60.0000000000",
        "-40.0000000000",
    ]


def test_provider_update_with_splits_is_blocked_and_target_revision_is_checked(
    stage2_database: Any,
) -> None:
    browser, _engine = stage2_database
    account = _account(browser)
    initial = _preview(
        browser,
        account["id"],
        amount="-100.00",
        provider_id="native-1",
        key="provider-first",
    )
    _publish(browser, initial)
    canonical = browser.get(
        "/v1/transactions", params={"account_id": account["id"]}
    ).json()[0]
    split = browser.put(
        f"/v1/transactions/{canonical['id']}/splits",
        json={
            "expected_revision": 1,
            "reason": "Split expense",
            "splits": [{"amount": "-100.00"}],
        },
    )
    assert split.status_code == 200, split.text

    changed = _preview(
        browser,
        account["id"],
        amount="-120.00",
        provider_id="native-1",
        key="provider-update",
    )
    row = changed["rows"][0]
    corrected = browser.patch(
        f"/v1/transaction-imports/{changed['id']}/rows/{row['id']}",
        json={
            "expected_review_revision": changed["review_revision"],
            "identity_resolution": "update",
            "duplicate_of_transaction_id": canonical["id"],
            "reason": "Provider correction",
        },
    )
    assert corrected.status_code == 200, corrected.text
    blocked = browser.post(
        f"/v1/transaction-imports/{changed['id']}/publish",
        json={
            "expected_review_revision": changed["review_revision"] + 1,
            "reason": "Publish correction",
        },
    )
    assert blocked.status_code == 422
    current = browser.get(
        "/v1/transactions", params={"account_id": account["id"]}
    ).json()[0]
    assert current["amount"] == "-100.0000000000"


def test_provider_update_rejects_target_revision_changed_after_review(
    stage2_database: Any,
) -> None:
    browser, _engine = stage2_database
    account = _account(browser)
    initial = _preview(
        browser,
        account["id"],
        amount="-100.00",
        provider_id="native-revision",
        key="provider-revision-first",
    )
    _publish(browser, initial)
    canonical = browser.get(
        "/v1/transactions", params={"account_id": account["id"]}
    ).json()[0]
    changed = _preview(
        browser,
        account["id"],
        amount="-120.00",
        provider_id="native-revision",
        key="provider-revision-update",
    )
    row = changed["rows"][0]
    corrected = browser.patch(
        f"/v1/transaction-imports/{changed['id']}/rows/{row['id']}",
        json={
            "expected_review_revision": changed["review_revision"],
            "identity_resolution": "update",
            "duplicate_of_transaction_id": canonical["id"],
            "reason": "Provider correction",
        },
    )
    assert corrected.status_code == 200, corrected.text
    changed_canonical = browser.patch(
        f"/v1/transactions/{canonical['id']}",
        json={
            "expected_revision": canonical["revision"],
            "reason": "Concurrent canonical review",
            "classification": "other",
        },
    )
    assert changed_canonical.status_code == 200, changed_canonical.text
    published = browser.post(
        f"/v1/transaction-imports/{changed['id']}/publish",
        json={
            "expected_review_revision": changed["review_revision"] + 1,
            "reason": "Publish correction",
        },
    )
    assert published.status_code == 409
    current = browser.get(
        "/v1/transactions", params={"account_id": account["id"]}
    ).json()[0]
    assert current["amount"] == "-100.0000000000"


def test_identity_resolution_rejects_explicit_null_required_fields(
    stage2_database: Any,
) -> None:
    browser, _engine = stage2_database
    account = _account(browser)
    initial = _preview(
        browser,
        account["id"],
        amount="-100.00",
        provider_id="native-2",
        key="provider-second",
    )
    _publish(browser, initial)
    existing = browser.get(
        "/v1/transactions", params={"account_id": account["id"]}
    ).json()[0]
    changed = _preview(
        browser,
        account["id"],
        amount="-90.00",
        provider_id="native-2",
        key="provider-third",
    )
    row = changed["rows"][0]
    for invalid in ({"posted_date": None}, {"currency": None}):
        response = browser.patch(
            f"/v1/transaction-imports/{changed['id']}/rows/{row['id']}",
            json={
                "expected_review_revision": changed["review_revision"],
                "identity_resolution": "update",
                "duplicate_of_transaction_id": existing["id"],
                "reason": "Must reject incomplete identity resolution",
                **invalid,
            },
        )
        assert response.status_code == 422


def test_category_rule_does_not_hide_unclassified_cash_flow_gap(
    stage2_database: Any,
) -> None:
    browser, _engine = stage2_database
    account = _account(browser)
    category = browser.post(
        "/v1/categories", json={"slug": "groceries", "display_name": "Groceries"}
    )
    assert category.status_code == 201, category.text
    rule = browser.post(
        "/v1/category-rules",
        json={"merchant": "Synthetic Bank Row", "category_id": category.json()["id"]},
    )
    assert rule.status_code == 201, rule.text
    review = _preview(
        browser,
        account["id"],
        amount="-42.00",
        provider_id="classified-by-category-only",
        key="category-only-rule",
    )
    _publish(browser, review)
    summary = browser.get(
        "/v1/finance/summary",
        params={
            "month": "2026-09-01",
            "as_of": "2026-10-01",
            "account_id": account["id"],
        },
    )
    assert summary.status_code == 200, summary.text
    total = summary.json()["currency_totals"][0]
    assert total["unclassified_count"] == 1
    assert total["unclassified_signed_amount"] == "-42.0000000000"
    assert total["net_spending"] == "0"
    assert any("unclassified" in item for item in summary.json()["coverage_gaps"])


def test_two_postgres_sessions_cannot_both_apply_the_same_revision(
    stage2_database: Any,
) -> None:
    _browser, engine = stage2_database
    if engine.dialect.name != "postgresql":
        pytest.skip("the concurrency check requires PostgreSQL 16")
    sessions = sessionmaker(engine, expire_on_commit=False)
    # Use the API fixture to create a transaction in this disposable database.
    browser = _browser
    account = _account(browser)
    transaction = _manual(browser, account["id"], amount="-8.00", key="concurrent-cas")
    barrier = Barrier(2)

    def edit(_slot: int) -> str:
        with sessions() as session:
            row = session.get(FinancialTransaction, UUID(transaction["id"]))
            assert row is not None
            barrier.wait(timeout=5)
            try:
                patch_transaction(
                    session,
                    row.id,
                    TransactionPatch(
                        expected_revision=1,
                        reason="Concurrent synthetic edit",
                        classification="expense",
                    ),
                )
                session.commit()
                return "committed"
            except TransactionConflict:
                session.rollback()
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(edit, [1, 2]))
    assert sorted(results) == ["committed", "conflict"]


def test_expired_cancelled_job_is_finalized_and_fences_old_worker(
    stage2_database: Any,
) -> None:
    _browser, engine = stage2_database
    sessions = sessionmaker(engine, expire_on_commit=False)
    now = utc_now()
    job_id = uuid4()
    with sessions.begin() as session:
        session.add(
            Job(
                id=job_id,
                job_type=jobs.PDF_PREVIEW_JOB,
                account_id=None,
                input_file_id=None,
                idempotency_key=f"expired-cancel:{job_id}",
                payload={},
                status="running",
                attempts=1,
                max_attempts=3,
                run_after=now - timedelta(minutes=2),
                lease_owner="crashed-worker",
                lease_until=now - timedelta(seconds=1),
                lease_generation=4,
                cancel_requested=True,
                progress_stage="processing",
                progress_current=0,
                progress_total=1,
                created_at=now - timedelta(minutes=2),
                updated_at=now - timedelta(minutes=2),
            )
        )
    claim = jobs.JobClaim(
        id=job_id,
        job_type=jobs.PDF_PREVIEW_JOB,
        account_id=None,
        input_file_id=None,
        payload={},
        owner="crashed-worker",
        generation=4,
        attempts=1,
        max_attempts=3,
    )
    assert jobs.claim_next_job(sessions, owner="replacement", lease_seconds=30) is None
    with sessions() as session:
        recovered = session.get(Job, job_id)
        assert recovered is not None
        assert recovered.status == "cancelled"
        assert recovered.lease_generation == 5
    assert not jobs.progress_job(
        sessions,
        claim,
        stage="stale-write",
        current=1,
        total=1,
        lease_seconds=30,
    )


def test_reupload_after_cancellation_creates_a_fresh_job_attempt(
    stage2_database: Any, tmp_path: Any
) -> None:
    browser, engine = stage2_database
    account = _account(browser)
    sessions = sessionmaker(engine, expire_on_commit=False)
    file_store = PrivateFileStore(tmp_path / "private")
    content = (
        Path(__file__).parents[3] / "fixtures/stage-2/synthetic-brokerage-statement.pdf"
    ).read_bytes()

    def enqueue() -> dict[str, Any]:
        return jobs.enqueue_pdf_preview(
            sessions,
            file_store,
            content=content,
            filename="synthetic-brokerage-statement.pdf",
            account_id=UUID(account["id"]),
            effective_date=date(2026, 9, 30),
            source_label="Synthetic brokerage",
            idempotency_key="same-upload-request",
            expected_account_revision=0,
            replace_existing=False,
            max_file_bytes=5_000_000,
            max_rows=500,
            max_pages=10,
            parser_timeout_seconds=10,
            max_attempts=3,
        )

    first = enqueue()
    with sessions.begin() as session:
        jobs.cancel_job(session, first["id"])
    second = enqueue()
    assert second["id"] != first["id"]
    assert second["status"] == "pending"
    with sessions() as session:
        original = session.get(Job, first["id"])
        retry = session.get(Job, second["id"])
        assert original is not None and original.status == "cancelled"
        assert retry is not None
        assert (
            retry.payload["import_idempotency_key"]
            != original.payload["import_idempotency_key"]
        )


def test_lost_lease_during_staging_cannot_persist_the_current_batch(
    stage2_database: Any, tmp_path: Any
) -> None:
    browser, engine = stage2_database
    account = _account(browser)
    sessions = sessionmaker(engine, expire_on_commit=False)
    count = 0

    def fence(_session: Any) -> None:
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("synthetic lease lost during staging")

    with pytest.raises(RuntimeError, match="lease lost"):
        imports.create_position_import(
            sessions,
            PrivateFileStore(tmp_path / "private"),
            content=b"identifier,quantity,price,currency\nUNKNOWN,1,10,USD\n",
            filename="synthetic-position.csv",
            account_id=UUID(account["id"]),
            effective_date=date(2026, 9, 30),
            source_label="Synthetic brokerage",
            mapping={
                "identifier": "identifier",
                "quantity": "quantity",
                "price": "price",
                "currency": "currency",
            },
            idempotency_key="lease-loss-staging",
            expected_account_revision=0,
            max_rows=10,
            write_fence=fence,
        )
    with sessions() as session:
        attempt = (
            session.query(ImportAttempt)
            .filter_by(idempotency_key="lease-loss-staging")
            .one()
        )
        assert attempt.status == "staging"
        assert session.query(ImportBatch).filter_by(import_id=attempt.id).count() == 0
        assert session.query(ImportRow).filter_by(import_id=attempt.id).count() == 0


@pytest.mark.parametrize("retry_key", ["completed-cancelled", "new-request"])
def test_reupload_after_cancelling_completed_pdf_review(
    stage2_database: Any, tmp_path: Path, retry_key: str
) -> None:
    from app.jobs.runner import _process_one

    browser, engine = stage2_database
    account = _account(browser)
    sessions = sessionmaker(engine, expire_on_commit=False)
    root = tmp_path / "private"
    file_store = PrivateFileStore(root)
    content = (
        Path(__file__).parents[3] / "fixtures/stage-2/synthetic-brokerage-statement.pdf"
    ).read_bytes()

    def enqueue(key: str) -> dict[str, Any]:
        return jobs.enqueue_pdf_preview(
            sessions,
            file_store,
            content=content,
            filename="synthetic.pdf",
            account_id=UUID(account["id"]),
            effective_date=date(2026, 9, 30),
            source_label="Synthetic brokerage",
            idempotency_key=key,
            expected_account_revision=0,
            replace_existing=False,
            max_file_bytes=5_000_000,
            max_rows=500,
            max_pages=10,
            parser_timeout_seconds=10,
            max_attempts=3,
        )

    first = enqueue("completed-cancelled")
    assert _process_one(sessions, file_store, worker_id="synthetic", lease_seconds=30)
    with sessions.begin() as session:
        completed = jobs.read_job(session, first["id"])
        assert completed["status"] == "completed", completed
        attempt = session.get(
            ImportAttempt, UUID(completed["result"]["position_import_id"])
        )
        assert attempt is not None
        imports.cancel_import(
            session,
            attempt.id,
            expected_revision=attempt.review_revision,
            reason="Cancel review",
        )
    retry = enqueue(retry_key)
    assert retry["id"] != first["id"]
    assert retry["status"] == "pending"
    assert enqueue(retry_key)["id"] == retry["id"]
    assert _process_one(sessions, file_store, worker_id="synthetic", lease_seconds=30)
    with sessions() as session:
        replacement = jobs.read_job(session, retry["id"])
        assert replacement["status"] == "completed", replacement
        assert (
            replacement["result"]["position_import_id"]
            != completed["result"]["position_import_id"]
        )
