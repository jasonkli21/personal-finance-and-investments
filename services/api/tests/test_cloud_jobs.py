"""Cloud invocation keeps durable enqueue, duplicate identity and worker fences."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Account, Base, Job
from app.jobs.cloud import trigger_job
from app.jobs.once import run_bounded
from app.main import create_app
from app.storage.file_store import PrivateFileStore


def test_failed_cloud_trigger_preserves_enqueue_and_repeat_reuses_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(
        "CLOUD_RUN_JOB",
        "projects/synthetic-project/locations/us-central1/jobs/finance-worker",
    )
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    account_id = uuid4()
    with Session(engine) as session:
        session.add(
            Account(
                id=account_id,
                name="Synthetic",
                account_type="taxable",
                base_currency="USD",
                active=True,
                source_type="manual",
            )
        )
        session.commit()
    app = create_app(engine=engine)
    calls = 0
    ids: list[object] = []

    def invoke(_resource: str) -> None:
        nonlocal calls
        calls += 1
        # Invocation sees committed state through a different session.
        with Session(engine) as session:
            ids.append(session.scalar(select(Job.id)))
        if calls == 1:
            raise OSError("synthetic unavailable")

    monkeypatch.setattr("app.jobs.cloud.trigger_job", invoke)
    headers = {
        "Content-Type": "application/pdf",
        "X-Account-Id": str(account_id),
        "X-Effective-Date": "2026-10-01",
        "X-Source-Label": "Synthetic",
        "X-Expected-Account-Revision": "0",
        "Idempotency-Key": "same-durable-upload",
    }
    with TestClient(app) as client:
        first = client.post(
            "/v1/imports/documents/positions/preview",
            content=b"%PDF-synthetic",
            headers=headers,
        )
        assert first.status_code == 503
        second = client.post(
            "/v1/imports/documents/positions/preview",
            content=b"%PDF-synthetic",
            headers=headers,
        )
        assert second.status_code == 202
        assert second.json()["id"] == str(ids[0])
        assert ids[0] == ids[1]
        assert second.json()["status"] == "pending"
        with Session(engine) as session:
            assert len(session.scalars(select(Job)).all()) == 1


def test_trigger_repeats_without_overrides_and_redacts_provider_error() -> None:
    class Client:
        calls: list[dict[str, Any]] = []

        def run_job(self, **kwargs: Any) -> None:
            self.calls.append(kwargs)

    client = Client()
    trigger_job("projects/synthetic/locations/us-central1/jobs/worker", client=client)
    trigger_job("projects/synthetic/locations/us-central1/jobs/worker", client=client)
    assert client.calls[0] == client.calls[1]
    assert set(client.calls[0]["request"]) == {"name"}

    class Broken:
        def run_job(self, **_kwargs: Any) -> None:
            raise RuntimeError("secret-provider-payload")

    with pytest.raises(OSError, match="invocation unavailable") as caught:
        trigger_job("synthetic", client=Broken())
    assert "secret-provider-payload" not in str(caught.value)


def test_bounded_worker_exits_when_idle_and_caps_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    store = PrivateFileStore(tmp_path / "private")
    monkeypatch.setattr("app.jobs.once._process_one", lambda *_args, **_kwargs: False)
    assert run_bounded(factory, store, lease_seconds=30) == 0
    monkeypatch.setattr("app.jobs.once._process_one", lambda *_args, **_kwargs: True)
    assert run_bounded(factory, store, lease_seconds=30, max_jobs=2) == 2
    ticks = iter([0.0, 241.0])
    assert run_bounded(factory, store, lease_seconds=30, clock=lambda: next(ticks)) == 0
    with pytest.raises(ValueError, match="bounds"):
        run_bounded(factory, store, lease_seconds=30, max_jobs=101)
    engine.dispose()


def test_trigger_client_initialization_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> None:
        raise RuntimeError("private-credential-initialization-detail")

    monkeypatch.setattr("google.cloud.run_v2.JobsClient", unavailable)
    with pytest.raises(OSError, match="invocation unavailable") as caught:
        trigger_job("synthetic")
    assert "private-credential" not in str(caught.value)
