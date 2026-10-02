"""Minimal API and database-readiness smoke tests."""

from typing import Self

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import app, create_app


def test_health_exposes_openapi_contract() -> None:
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]


def test_ready_reports_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise psycopg.OperationalError("synthetic connection failure")

    monkeypatch.setattr(psycopg, "connect", fail_connect)
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_ready_uses_discrete_connection_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_HOST", "db")
    monkeypatch.setenv("DATABASE_PORT", "5432")
    monkeypatch.setenv("DATABASE_USER", "portfolio")
    monkeypatch.setenv("DATABASE_PASSWORD", "p@ss:/?#% word")
    monkeypatch.setenv("DATABASE_NAME", "portfolio")
    calls: list[dict[str, object]] = []

    class FakeConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            assert query == "SELECT 1"

    def connect(**kwargs: object) -> FakeConnection:
        calls.append(kwargs)
        return FakeConnection()

    monkeypatch.setattr(psycopg, "connect", connect)
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 200
    assert calls == [
        {
            "host": "db",
            "port": 5432,
            "user": "portfolio",
            "password": "p@ss:/?#% word",
            "dbname": "portfolio",
            "connect_timeout": 2,
        }
    ]


def test_ready_passes_explicit_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit-host/explicit-db")
    calls: list[dict[str, object]] = []

    class FakeConnection:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, query: str) -> None:
            assert query == "SELECT 1"

    def connect(**kwargs: object) -> FakeConnection:
        calls.append(kwargs)
        return FakeConnection()

    monkeypatch.setattr(psycopg, "connect", connect)
    response = TestClient(create_app()).get("/health/ready")

    assert response.status_code == 200
    assert calls == [
        {"conninfo": "postgresql://explicit-host/explicit-db", "connect_timeout": 2}
    ]
