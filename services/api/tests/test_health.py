"""Minimal API and database-readiness smoke tests."""

import asyncio
from pathlib import Path
from typing import Self, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.main import app, create_app


class FakeConnection:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, query: object) -> None:
        assert str(query) == "SELECT 1"


class FakeEngine:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def connect(self) -> FakeConnection:
        if self.fail:
            raise OperationalError("SELECT 1", {}, RuntimeError("synthetic outage"))
        return FakeConnection()

    def dispose(self) -> None:
        return None


def test_health_exposes_openapi_contract() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]


def test_ready_reports_database_failure() -> None:
    response = TestClient(create_app(engine=cast(Engine, FakeEngine(fail=True)))).get(
        "/health/ready"
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_ready_uses_database_engine() -> None:
    response = TestClient(create_app(engine=cast(Engine, FakeEngine()))).get(
        "/health/ready"
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_failed_worker_does_not_skip_pool_disposal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "true")
    disposed = False

    async def failed_worker(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Synthetic worker failure")

    def dispose() -> None:
        nonlocal disposed
        disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr("app.jobs.runner.run_worker", failed_worker)
    application = create_app(engine=cast(Engine, engine))

    async def lifespan() -> None:
        async with application.router.lifespan_context(application):
            await asyncio.sleep(0)

    with pytest.raises(RuntimeError, match="Synthetic worker failure"):
        asyncio.run(lifespan())
    assert disposed
