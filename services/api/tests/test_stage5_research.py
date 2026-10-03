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

from app.db.models import (
    Account,
    Base,
    FinancialTransaction,
    Issuer,
    PositionSnapshot,
    ReportedFact,
    ResearchDocument,
    ResearchResult,
    ResearchRun,
)
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


def test_company_view_and_comparison_require_comparable_fiscal_facts(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    documents = _add_documents(research_client, issuer_id)
    facts = []
    for index, fact in enumerate(_fixture()["facts"]):
        response = research_client.post(
            "/v1/research/facts",
            json={**fact, "document_id": documents[index]["id"]},
        )
        assert response.status_code == 201, response.text
        facts.append(response.json())

    company = research_client.get(f"/v1/research/issuers/{issuer_id}")
    assert company.status_code == 200, company.text
    assert company.json()["issuer"]["display_name"] == "Synthetic Research Inc"
    assert len(company.json()["documents"]) == 2
    assert len(company.json()["facts"]) == 2

    comparison = research_client.post(
        "/v1/research/comparisons",
        json={
            "prior_fact_id": facts[0]["id"],
            "current_fact_id": facts[1]["id"],
        },
    )
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["status"] == "comparable"
    assert comparison.json()["absolute_change"] == "20000000"
    assert comparison.json()["percent_change"] == "20"
    assert comparison.json()["diagnostics"] == []

    incompatible = research_client.post(
        "/v1/research/facts",
        json={
            **_fixture()["facts"][1],
            "document_id": documents[1]["id"],
            "idempotency_key": "synthetic-revenue-other-unit",
            "unit": "shares",
        },
    )
    assert incompatible.status_code == 201
    unavailable = research_client.post(
        "/v1/research/comparisons",
        json={
            "prior_fact_id": facts[0]["id"],
            "current_fact_id": incompatible.json()["id"],
        },
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["status"] == "unavailable"
    assert "unit_mismatch" in unavailable.json()["diagnostics"]
    assert unavailable.json()["percent_change"] is None

    different_period = research_client.post(
        "/v1/research/facts",
        json={
            **_fixture()["facts"][1],
            "document_id": documents[1]["id"],
            "idempotency_key": "synthetic-revenue-other-fiscal-period",
            "fiscal_period": "Q3",
        },
    )
    assert different_period.status_code == 201
    period_comparison = research_client.post(
        "/v1/research/comparisons",
        json={
            "prior_fact_id": facts[0]["id"],
            "current_fact_id": different_period.json()["id"],
        },
    )
    assert period_comparison.status_code == 200
    assert period_comparison.json()["status"] == "unavailable"
    assert "fiscal_period_mismatch" in period_comparison.json()["diagnostics"]

    zero_baseline = research_client.post(
        "/v1/research/facts",
        json={
            **_fixture()["facts"][0],
            "document_id": documents[0]["id"],
            "normalized_value": "0",
            "raw_value": "0",
            "idempotency_key": "synthetic-revenue-zero-baseline",
        },
    )
    assert zero_baseline.status_code == 201
    zero_comparison = research_client.post(
        "/v1/research/comparisons",
        json={
            "prior_fact_id": zero_baseline.json()["id"],
            "current_fact_id": facts[1]["id"],
        },
    )
    assert zero_comparison.status_code == 200
    assert zero_comparison.json()["status"] == "comparable"
    assert zero_comparison.json()["absolute_change"] == "120000000"
    assert zero_comparison.json()["percent_change"] is None
    assert (
        "percent_change_unavailable_nonpositive_baseline"
        in zero_comparison.json()["diagnostics"]
    )


def test_offline_baseline_freezes_cited_facts_and_is_idempotent(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    documents = _add_documents(research_client, issuer_id)
    facts = []
    for index, fact in enumerate(_fixture()["facts"]):
        response = research_client.post(
            "/v1/research/facts",
            json={**fact, "document_id": documents[index]["id"]},
        )
        assert response.status_code == 201, response.text
        facts.append(response.json())

    payload = {
        "issuer_id": issuer_id,
        "question": "Compare the synthetic annual reported revenue",
        "fact_ids": [facts[0]["id"], facts[1]["id"]],
        "idempotency_key": "synthetic-baseline-run-1",
    }
    first = research_client.post("/v1/research/runs", json=payload)
    again = research_client.post("/v1/research/runs", json=payload)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert first.json()["duplicate"] is False
    assert again.json()["duplicate"] is True
    assert first.json()["validation_status"] == "source_links_checked_unverified_values"
    assert first.json()["result"]["mode"] == "offline_deterministic"
    assert first.json()["result"]["inferences"] == []
    assert len(first.json()["result"]["citations"]) == 2
    assert (
        first.json()["result"]["citations"][1]["source_url"]
        == documents[1]["source_url"]
    )

    changed = {**payload, "question": "Changed question, reused key"}
    conflict = research_client.post("/v1/research/runs", json=changed)
    assert conflict.status_code == 409

    loaded = research_client.get(f"/v1/research/runs/{first.json()['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["result_hash"] == first.json()["result_hash"]

    factory = cast(Any, research_client.app).state.session_factory
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ResearchRun)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchResult)) == 1
        assert session.scalar(select(func.count()).select_from(Account)) == 0
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
        assert (
            session.scalar(select(func.count()).select_from(FinancialTransaction)) == 0
        )
