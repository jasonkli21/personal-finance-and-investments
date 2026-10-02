"""Stage 1 feature gate on an explicitly disposable, exclusive DSQL cluster.

Feature writes use the same bounded domain paths as PG16. Cleanup deletes only
new IDs in batches of 200, keeping the migration ledger. No Alembic shortcut.
"""

from __future__ import annotations

from os import environ
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import test_reports as report_cases
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from test_dsql_integration import _open_engines
from test_funds import (
    test_bounded_fund_publication_duplicates_history_and_anomalies as bounded_fund,
)
from test_funds import (
    test_interrupted_publication_is_hidden_then_resumes as interrupted_fund,
)
from test_reports import (
    test_golden_filters_export_freeze_restart_and_integrity as golden,
)

from app.db.dsql_migrations import run_dsql_migrations
from app.db.models import Base
from app.main import create_app

pytestmark = pytest.mark.skipif(
    environ.get("RUN_DSQL_INTEGRATION") != "1"
    or environ.get("DSQL_TEST_CLUSTER") != "disposable",
    reason="Stage 1 requires explicit opt-in and a disposable Aurora DSQL cluster",
)


@pytest.fixture
def cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    migration, engine = _open_engines()
    run_dsql_migrations(migration)
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    tables = Base.metadata.tables
    with engine.connect() as conn:
        before: dict[str, set[UUID]] = {
            name: set(conn.scalars(select(table.c.id)))
            for name, table in tables.items()
        }
    browser = TestClient(create_app(engine=engine))
    try:
        yield browser, engine
    finally:
        with engine.connect() as conn:
            added: dict[str, list[UUID]] = {
                name: list(set(conn.scalars(select(table.c.id))) - before[name])
                for name, table in tables.items()
            }
        for name, fields in [
            ("accounts", {"current_position_snapshot_id": None}),
            (
                "imports",
                {
                    "staging_snapshot_id": None,
                    "published_snapshot_id": None,
                    "duplicate_of_import_id": None,
                },
            ),
        ]:
            for offset in range(0, len(added[name]), 200):
                with engine.begin() as conn:
                    conn.execute(
                        update(tables[name])
                        .where(
                            tables[name].c.id.in_(added[name][offset : offset + 200])
                        )
                        .values(**fields)
                    )
        order = [
            "portfolio_calculations",
            "fund_lines",
            "fund_snapshots",
            "import_review_events",
            "import_batches",
            "import_rows",
            "imports",
            "private_files",
            "position_snapshot_lines",
            "position_snapshots",
            "accounts",
            "quotes",
            "security_issuer_mapping_events",
            "security_identifiers",
            "securities",
            "issuer_aliases",
            "issuers",
        ]
        for name in order:
            for offset in range(0, len(added[name]), 200):
                with engine.begin() as conn:
                    conn.execute(
                        delete(tables[name]).where(
                            tables[name].c.id.in_(added[name][offset : offset + 200])
                        )
                    )
        engine.dispose()
        migration.dispose()


def test_real_dsql_stage1_golden_and_frozen_report(
    cloud: Any, monkeypatch: Any
) -> None:
    golden(cloud, monkeypatch)


def test_real_dsql_stage1_502_rows_duplicate_and_history(cloud: Any) -> None:
    bounded_fund(cloud)


def test_real_dsql_stage1_partial_staging_recovery(
    cloud: Any, monkeypatch: Any
) -> None:
    interrupted_fund(cloud, monkeypatch)


def test_real_dsql_stage1_concurrent_publication(cloud: Any) -> None:
    report_cases.test_concurrent_import_publication_and_old_duplicate_do_not_move_head(
        cloud
    )
