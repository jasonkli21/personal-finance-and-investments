"""Regression coverage for independent Stage 2 review findings."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import Base, DocumentImport, ImportAttempt, PrivateFile
from app.domains.documents import read_document_import
from app.ingestion.brokerage_pdf import extract_pdf_pages
from app.main import create_app


def test_pdf_parser_child_receives_no_parent_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-secret")
    monkeypatch.setenv("GCP_PRIVATE_TEST_SECRET", "synthetic-secret")
    captured: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args[0],
            0,
            b'{"pages":[{"page":1,"text":"Synthetic statement"}]}',
            b"",
        )

    monkeypatch.setattr("app.ingestion.brokerage_pdf.subprocess.run", fake_run)

    pages = extract_pdf_pages(b"%PDF-synthetic", max_pages=17)

    assert pages == [{"page": 1, "text": "Synthetic statement"}]
    child_environment = captured["env"]
    assert child_environment["PDF_MAX_PAGES"] == "17"
    assert "DATABASE_URL" not in child_environment
    assert "GCP_PRIVATE_TEST_SECRET" not in child_environment


@pytest.mark.parametrize("attempt_status", ["published", "cancelled"])
def test_document_read_status_tracks_linked_position_import(
    attempt_status: str,
) -> None:
    document_id = uuid4()
    file_id = uuid4()
    import_id = uuid4()
    account_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        file_id=file_id,
        position_import_id=import_id,
        account_id=account_id,
        effective_date=date(2026, 9, 30),
        source_label="Synthetic brokerage statement",
        parser_version="brokerage-text-pdf/test",
        status="review",
        row_count=1,
        diagnostics={"review_required": True},
    )
    attempt = SimpleNamespace(status=attempt_status)
    source = SimpleNamespace(original_name="synthetic-statement.pdf")
    records = {
        DocumentImport: document,
        ImportAttempt: attempt,
        PrivateFile: source,
    }

    class FakeSession:
        @staticmethod
        def get(model: type[Any], _identity: object) -> Any:
            return records[model]

    result = read_document_import(cast(Session, FakeSession()), document_id)

    assert result["status"] == attempt_status
    assert result["position_import_status"] == attempt_status


def test_transaction_csv_uses_configured_upload_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_limit = 6_000_000
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("MAX_IMPORT_FILE_BYTES", str(configured_limit))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    monkeypatch.setenv("PERSONAL_AI_ENABLED", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(engine=engine)
    content = (
        b"posted,amount,description\n2026-09-30,-12.50,Synthetic purchase\n"
        + b"\n" * 5_000_001
    )
    assert 5_000_000 < len(content) < configured_limit

    try:
        with TestClient(app) as client:
            account_response = client.post(
                "/v1/accounts",
                json={
                    "name": "Synthetic bank account",
                    "account_type": "checking",
                    "base_currency": "USD",
                },
            )
            assert account_response.status_code == 201
            account_id = account_response.json()["id"]
            response = client.post(
                "/v1/imports/transactions/preview",
                content=content,
                headers={
                    "Content-Type": "text/csv",
                    "X-Account-Id": account_id,
                    "X-Source-Label": "Synthetic bank CSV",
                    "X-Column-Mapping": json.dumps(
                        {
                            "posted_date": "posted",
                            "amount": "amount",
                            "description": "description",
                        }
                    ),
                    "X-File-Name": "synthetic.csv",
                    "Idempotency-Key": "synthetic-large-csv-review",
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["row_count"] == 1
    finally:
        engine.dispose()
