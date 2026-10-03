"""Offline source and fact record checks use only synthetic SEC-shaped data."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from app.db.models import Base, Issuer, ReportedFact, ResearchDocument
from app.main import create_app


@pytest.fixture
def research_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(tmp_path / "private"))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with TestClient(create_app(engine=engine)) as client:
        yield client
    engine.dispose()


def _fixture() -> dict[str, Any]:
    path = (
        Path(__file__).parents[3] / "fixtures/stage-5/synthetic-company-research.json"
    )
    return cast(dict[str, Any], json.loads(path.read_text()))


def _issuer(client: TestClient) -> str:
    factory = cast(Any, client.app).state.session_factory
    identifier = uuid4()
    with factory() as session:
        session.add(
            Issuer(
                id=identifier,
                normalized_name="synthetic research inc",
                display_name="Synthetic Research Inc",
            )
        )
        session.commit()
    return str(identifier)


def _add_documents(client: TestClient, issuer_id: str) -> list[dict[str, Any]]:
    result = []
    for document in _fixture()["documents"]:
        response = client.post(
            "/v1/research/documents",
            json={"issuer_id": issuer_id, **document},
        )
        assert response.status_code == 201, response.text
        result.append(response.json())
    return result


def test_source_registration_is_explicitly_unverified_and_idempotent(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    document = _fixture()["documents"][0]
    first = research_client.post(
        "/v1/research/documents", json={"issuer_id": issuer_id, **document}
    )
    again = research_client.post(
        "/v1/research/documents", json={"issuer_id": issuer_id, **document}
    )

    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["source_status"] == "user_supplied_unverified"
    assert first.json()["duplicate"] is False
    assert again.json()["duplicate"] is True

    changed = {**document, "title": "Different title for same accession"}
    conflict = research_client.post(
        "/v1/research/documents", json={"issuer_id": issuer_id, **changed}
    )
    assert conflict.status_code == 409


def test_document_rejects_non_sec_urls_unknown_issuers_and_bad_periods(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    document = _fixture()["documents"][0]

    bad_url = research_client.post(
        "/v1/research/documents",
        json={
            "issuer_id": issuer_id,
            **document,
            "source_url": "http://localhost/private",
        },
    )
    assert bad_url.status_code == 422

    bad_period = research_client.post(
        "/v1/research/documents",
        json={
            "issuer_id": issuer_id,
            **document,
            "period_start": "2025-01-01",
            "period_end": "2024-01-01",
        },
    )
    assert bad_period.status_code == 422

    missing_issuer = research_client.post(
        "/v1/research/documents",
        json={"issuer_id": str(uuid4()), **document},
    )
    assert missing_issuer.status_code == 404


def test_reported_facts_are_exact_decimal_and_idempotent(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    documents = _add_documents(research_client, issuer_id)
    fact_template = _fixture()["facts"][0]
    payload = {**fact_template, "document_id": documents[0]["id"]}
    first = research_client.post("/v1/research/facts", json=payload)
    again = research_client.post("/v1/research/facts", json=payload)

    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["normalized_value"] == "100000000"
    assert first.json()["quality_status"] == "user_supplied_unverified"
    assert first.json()["duplicate"] is False
    assert again.json()["duplicate"] is True

    changed = {**payload, "raw_value": "101000000"}
    conflict = research_client.post("/v1/research/facts", json=changed)
    assert conflict.status_code == 409

    invalid_period = research_client.post(
        "/v1/research/facts",
        json={**payload, "idempotency_key": "bad-period", "instant": "2024-12-31"},
    )
    assert invalid_period.status_code == 422

    invalid_precision = research_client.post(
        "/v1/research/facts",
        json={
            **payload,
            "idempotency_key": "bad-precision",
            "normalized_value": "1234567890123456789.1",
        },
    )
    assert invalid_precision.status_code == 422


def test_research_reads_are_bounded_and_do_not_change_financial_records(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    documents = _add_documents(research_client, issuer_id)
    for index, fact in enumerate(_fixture()["facts"]):
        research_client.post(
            "/v1/research/facts",
            json={**fact, "document_id": documents[index]["id"]},
        )

    document_response = research_client.get(
        f"/v1/research/issuers/{issuer_id}/documents"
    )
    fact_response = research_client.get(
        f"/v1/research/documents/{documents[0]['id']}/facts"
    )
    assert document_response.status_code == fact_response.status_code == 200
    assert len(document_response.json()) == 2
    assert len(fact_response.json()) == 1

    factory = cast(Any, research_client.app).state.session_factory
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ResearchDocument)) == 2
        assert session.scalar(select(func.count()).select_from(ReportedFact)) == 2
        assert session.scalar(select(func.count()).select_from(Issuer)) == 1
