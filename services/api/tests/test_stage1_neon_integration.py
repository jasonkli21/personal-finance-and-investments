"""Stage 1 feature gate on an explicitly disposable, exclusive Neon branch.

Uses ordinary Alembic and the same bounded Finance domain paths.
"""

from __future__ import annotations

from os import environ
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import test_reports as report_cases
from fastapi.testclient import TestClient
from sqlalchemy import insert
from test_core_schema import _migrate, _reset_schema
from test_funds import (
    test_bounded_fund_publication_duplicates_history_and_anomalies as bounded_fund,
)
from test_funds import (
    test_interrupted_publication_is_hidden_then_resumes as interrupted_fund,
)
from test_neon_integration import _open_engines
from test_reports import (
    test_golden_filters_export_freeze_restart_and_integrity as golden,
)

from app.db.models import Security
from app.main import create_app

pytestmark = pytest.mark.skipif(
    environ.get("RUN_NEON_INTEGRATION") != "1"
    or environ.get("NEON_TEST_DATABASE") != "disposable",
    reason="Stage 1 requires explicit opt-in and a disposable Neon branch",
)


@pytest.fixture
def cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    migration, engine = _open_engines()
    _reset_schema(migration)
    _migrate(environ["NEON_TEST_MIGRATION_DATABASE_URL"])
    # This suite proves DB behavior. Hosted auth/GCS have separate release gates.
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("FILE_STORAGE_BACKEND", "local")
    monkeypatch.setenv("PERSONAL_AI_ENABLED", "false")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DEMO_MODE", "false")
    for key in ("DATABASE_URL", "MIGRATION_DATABASE_URL", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    with TestClient(create_app(engine=engine)) as browser:
        yield browser, engine
    migration.dispose()


def test_real_neon_stage1_golden_and_frozen_report(
    cloud: Any, monkeypatch: Any
) -> None:
    golden(cloud, monkeypatch)


def test_real_neon_stage1_502_rows_duplicate_and_history(cloud: Any) -> None:
    bounded_fund(cloud)


def test_real_neon_stage1_partial_staging_recovery(
    cloud: Any, monkeypatch: Any
) -> None:
    interrupted_fund(cloud, monkeypatch)


def test_real_neon_stage1_concurrent_publication(cloud: Any) -> None:
    report_cases.test_concurrent_import_publication_and_old_duplicate_do_not_move_head(
        cloud
    )


def test_real_neon_configured_safe_batch_limit_rejects_extra_row(
    cloud: Any,
) -> None:
    browser, engine = cloud
    fund_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(Security).values(
                id=fund_id,
                security_type="etf",
                display_ticker="SYNBATCH",
                name="Synthetic safe-batch ETF",
                currency="USD",
            )
        )
    limit = browser.app.state.max_import_rows
    content = "Ticker,Name,Weight\n" + "".join(
        f"SYN{index},Synthetic {index},1\n" for index in range(limit + 1)
    )
    response = browser.post(
        f"/v1/funds/{fund_id}/upload",
        content=content.encode(),
        headers={
            "Content-Type": "text/csv",
            "X-Effective-Date": "2026-10-03",
            "Idempotency-Key": f"safe-batch-{fund_id.hex}",
            "X-Source-Label": "Synthetic batch-boundary test",
            "X-Fund-Format": "manual",
            "X-Weight-Unit": "percent",
            "X-Column-Mapping": (
                '{"identifier":"Ticker","name":"Name","weight":"Weight"}'
            ),
        },
    )
    assert response.status_code == 422
    assert "configured row limit" in response.json()["detail"]
