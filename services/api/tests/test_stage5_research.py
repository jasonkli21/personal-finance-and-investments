"""Offline source and fact record checks use only synthetic SEC-shaped data."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool
from test_funds import catalog as create_fund_security
from test_funds import upload as upload_fund

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
    ResearchRunContext,
    ResearchThesisNote,
    ResearchWatchlistEvent,
    Security,
)
from app.integrations.personal_ai import DisabledPersonalAIClient
from app.integrations.research_evidence import (
    EvidenceScopeDocument,
    ResearchEvidenceEligibility,
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


def _evaluation_fixture() -> dict[str, Any]:
    path = (
        Path(__file__).parents[3]
        / "fixtures/stage-5/synthetic-research-evaluation.json"
    )
    return cast(dict[str, Any], json.loads(path.read_text()))


def _issuer(client: TestClient, *, name: str = "Synthetic Research Inc") -> str:
    response = client.post("/v1/issuers", json={"display_name": name})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


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

    assert first.status_code == 201, first.text
    assert again.status_code == 201, again.text
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


def test_stage5_offline_evaluation_citations_privacy_and_disabled_parity(
    research_client: TestClient,
) -> None:
    evaluation = _evaluation_fixture()
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

    comparison_case = evaluation["comparison"]
    comparison = research_client.post(
        "/v1/research/comparisons",
        json={
            "prior_fact_id": facts[comparison_case["prior_fact_index"]]["id"],
            "current_fact_id": facts[comparison_case["current_fact_index"]]["id"],
        },
    )
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["status"] == comparison_case["expected_status"]
    assert (
        comparison.json()["absolute_change"]
        == comparison_case["expected_absolute_change"]
    )
    assert (
        comparison.json()["percent_change"]
        == comparison_case["expected_percent_change"]
    )

    note_text = evaluation["untrusted_thesis_note"]
    note = research_client.post(
        "/v1/research/thesis-notes",
        json={
            "issuer_id": issuer_id,
            "text": note_text,
            "idempotency_key": "synthetic-evaluation-hostile-thesis",
        },
    )
    assert note.status_code == 201, note.text

    factory = cast(Any, research_client.app).state.session_factory
    with factory() as session:
        canonical_counts_before = {
            model.__name__: session.scalar(select(func.count()).select_from(model))
            for model in (Account, PositionSnapshot, FinancialTransaction)
        }

    baseline = research_client.post(
        "/v1/research/runs",
        json={
            "issuer_id": issuer_id,
            "question": "Compare synthetic annual revenue against the saved thesis",
            "fact_ids": [item["id"] for item in facts],
            "idempotency_key": "synthetic-evaluation-offline-run",
            "thesis_note_id": note.json()["id"],
        },
    )
    assert baseline.status_code == 201, baseline.text
    result = baseline.json()["result"]
    assert result["mode"] == evaluation["expected_result_mode"]
    assert result["inferences"] == evaluation["expected_inferences"]
    assert result["thesis_note"]["text"] == note_text
    assert len(result["citations"]) == 2
    assert {
        citation["fact_id"]: citation for citation in result["citations"]
    }.keys() == {item["id"] for item in facts}
    for index, (fact, document) in enumerate(zip(facts, documents, strict=True)):
        citation = next(
            item for item in result["citations"] if item["fact_id"] == fact["id"]
        )
        assert citation["document_id"] == document["id"]
        assert citation["accession_number"] == document["accession_number"]
        assert citation["source_url"] == document["source_url"]
        assert citation["quality_status"] == "user_supplied_unverified"
        assert citation["fact_id"] == facts[index]["id"]

    assert note_text not in json.dumps(result["citations"])
    assert (
        "No shared research service or model synthesis was run." in result["unknowns"]
    )
    assert isinstance(
        cast(Any, research_client.app).state.personal_ai_client,
        DisabledPersonalAIClient,
    )

    eligibility = ResearchEvidenceEligibility(
        issuer_id=UUID(issuer_id),
        allowed_documents=[
            EvidenceScopeDocument(
                document_id=UUID(document["id"]),
                issuer_id=UUID(issuer_id),
                accession_number=document["accession_number"],
                source_url=document["source_url"],
                filing_date=document["filing_date"],
                source_status="user_supplied_unverified",
            )
            for document in documents
        ],
        as_of=datetime(2026, 10, 3, tzinfo=UTC),
    )
    eligibility_payload = eligibility.model_dump(mode="json")
    assert set(eligibility_payload) == {
        "schema_version",
        "issuer_id",
        "allowed_documents",
        "as_of",
        "max_age_days",
        "minimum_evidence",
        "max_items",
        "max_excerpt_bytes",
        "max_total_bytes",
    }
    assert all(
        set(document)
        == {
            "document_id",
            "issuer_id",
            "accession_number",
            "source_url",
            "filing_date",
            "source_status",
        }
        for document in eligibility_payload["allowed_documents"]
    )
    serialized_eligibility = json.dumps(eligibility_payload)
    assert note_text not in serialized_eligibility
    assert not any(
        token in serialized_eligibility.lower()
        for token in ("account", "balance", "portfolio", "thesis")
    )

    with factory() as session:
        canonical_counts_after = {
            model.__name__: session.scalar(select(func.count()).select_from(model))
            for model in (Account, PositionSnapshot, FinancialTransaction)
        }
    assert canonical_counts_after == canonical_counts_before


def test_portfolio_context_notes_and_watchlist_are_frozen_locally(
    research_client: TestClient,
) -> None:
    issuer_id = _issuer(research_client)
    nvda_uuid = uuid4()
    nvda_id = str(nvda_uuid)
    factory = cast(Any, research_client.app).state.session_factory
    with factory() as session:
        session.add(
            Security(
                id=nvda_uuid,
                security_type="equity",
                display_ticker="NVDA",
                name="Synthetic NVIDIA",
                currency="USD",
                issuer_id=UUID(issuer_id),
            )
        )
        session.commit()
    fa_id = create_fund_security(research_client, "FA")
    fb_id = create_fund_security(research_client, "FB")
    account = research_client.post(
        "/v1/accounts",
        json={
            "name": "Synthetic brokerage",
            "account_type": "taxable",
            "base_currency": "USD",
        },
    )
    assert account.status_code == 201, account.text
    account_id = account.json()["id"]
    positions = research_client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 0,
            "effective_date": "2026-10-01",
            "positions": [
                {
                    "security_id": nvda_id,
                    "quantity": "300",
                    "reported_price": "100",
                    "currency": "USD",
                },
                {
                    "security_id": fa_id,
                    "quantity": "500",
                    "reported_price": "100",
                    "currency": "USD",
                },
                {
                    "security_id": fb_id,
                    "quantity": "200",
                    "reported_price": "100",
                    "currency": "USD",
                },
            ],
        },
    )
    assert positions.status_code == 200, positions.text
    for fund_id, weight in ((fa_id, "8"), (fb_id, "6")):
        uploaded = upload_fund(
            research_client,
            fund_id,
            f"ticker,weight,type\nNVDA,{weight},equity\nOTHER,92,equity\n".encode(),
        )
        published = research_client.post(
            f"/v1/fund-imports/{uploaded['id']}/publish",
            json={"expected_review_revision": 1},
        )
        assert published.status_code == 200, published.text

    docs = _add_documents(research_client, issuer_id)
    facts = []
    for index, fact in enumerate(_fixture()["facts"]):
        response = research_client.post(
            "/v1/research/facts",
            json={**fact, "document_id": docs[index]["id"]},
        )
        assert response.status_code == 201, response.text
        facts.append(response.json())

    first_note = research_client.post(
        "/v1/research/thesis-notes",
        json={
            "issuer_id": issuer_id,
            "text": "Synthetic thesis note version one.",
            "idempotency_key": "synthetic-thesis-v1",
        },
    )
    second_note = research_client.post(
        "/v1/research/thesis-notes",
        json={
            "issuer_id": issuer_id,
            "text": "Synthetic thesis note version two.",
            "idempotency_key": "synthetic-thesis-v2",
        },
    )
    assert first_note.status_code == second_note.status_code == 201
    assert first_note.json()["version"] == 1
    assert second_note.json()["version"] == 2
    assert (
        research_client.get(f"/v1/research/issuers/{issuer_id}/thesis-notes").json()[0][
            "id"
        ]
        == second_note.json()["id"]
    )

    watchlist = f"/v1/research/issuers/{issuer_id}/watchlist"
    add_payload = {"action": "added", "idempotency_key": "watchlist-add-1"}
    added = research_client.post(f"{watchlist}/events", json=add_payload)
    duplicate_add = research_client.post(f"{watchlist}/events", json=add_payload)
    repeated_add = research_client.post(
        f"{watchlist}/events",
        json={"action": "added", "idempotency_key": "watchlist-add-noop"},
    )
    removed = research_client.post(
        f"{watchlist}/events",
        json={"action": "removed", "idempotency_key": "watchlist-remove-1"},
    )
    assert (
        added.status_code
        == duplicate_add.status_code
        == repeated_add.status_code
        == removed.status_code
        == 201
    )
    assert added.json()["version"] == 1 and duplicate_add.json()["duplicate"] is True
    assert repeated_add.json()["version"] == 2
    assert removed.json()["version"] == 3
    readded = research_client.post(
        f"{watchlist}/events",
        json={"action": "added", "idempotency_key": "watchlist-add-2"},
    )
    assert readded.json()["version"] == 4
    assert research_client.get(watchlist).json()["active"] is True
    assert [
        entry["issuer_id"]
        for entry in research_client.get("/v1/research/watchlist").json()
    ] == [issuer_id]

    portfolio_report = research_client.post("/v1/portfolio/reports", json={})
    assert portfolio_report.status_code == 200, portfolio_report.text
    report_id = portfolio_report.json()["id"]
    baseline_payload = {
        "issuer_id": issuer_id,
        "question": "Review synthetic company context",
        "fact_ids": [item["id"] for item in facts],
        "idempotency_key": "synthetic-context-run",
        "portfolio_report_id": report_id,
        "thesis_note_id": first_note.json()["id"],
    }
    saved = research_client.post("/v1/research/runs", json=baseline_payload)
    assert saved.status_code == 201, saved.text
    context = saved.json()["result"]["portfolio_context"]
    assert context["status"] == "matched"
    assert context["direct_exposure"] == "30000"
    assert context["indirect_exposure"] == "5200"
    assert context["total_exposure"] == "35200"
    assert (
        sum(1 for row in context["contributions"] if row["exposure_kind"] == "direct")
        == 1
    )
    assert (
        sum(1 for row in context["contributions"] if row["exposure_kind"] == "indirect")
        == 2
    )
    assert context["account_ids"] == [account_id]
    assert saved.json()["result"]["thesis_note"]["text"] == first_note.json()["text"]

    updated = research_client.put(
        f"/v1/accounts/{account_id}/positions",
        json={
            "expected_revision": 1,
            "effective_date": "2026-10-02",
            "positions": [
                {
                    "security_id": nvda_id,
                    "quantity": "400",
                    "reported_price": "100",
                    "currency": "USD",
                },
                {
                    "security_id": fa_id,
                    "quantity": "500",
                    "reported_price": "100",
                    "currency": "USD",
                },
                {
                    "security_id": fb_id,
                    "quantity": "200",
                    "reported_price": "100",
                    "currency": "USD",
                },
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    updated_note = research_client.post(
        "/v1/research/thesis-notes",
        json={
            "issuer_id": issuer_id,
            "text": "A later note must not rewrite the saved baseline.",
            "idempotency_key": "synthetic-thesis-v3",
        },
    )
    assert updated_note.json()["version"] == 3
    loaded = research_client.get(f"/v1/research/runs/{saved.json()['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["result"]["portfolio_context"]["total_exposure"] == "35200"
    assert loaded.json()["result"]["thesis_note"]["id"] == first_note.json()["id"]

    new_report = research_client.post("/v1/portfolio/reports", json={})
    assert new_report.status_code == 200
    new_run = research_client.post(
        "/v1/research/runs",
        json={
            **baseline_payload,
            "idempotency_key": "synthetic-context-run-after-position-change",
            "portfolio_report_id": new_report.json()["id"],
            "thesis_note_id": updated_note.json()["id"],
        },
    )
    assert new_run.status_code == 201, new_run.text
    assert new_run.json()["result"]["portfolio_context"]["total_exposure"] == "45200"
    assert new_run.json()["result"]["thesis_note"]["version"] == 3
    assert (
        research_client.get(f"/v1/research/runs/{saved.json()['id']}").json()["result"][
            "portfolio_context"
        ]["total_exposure"]
        == "35200"
    )

    unmapped_issuer = _issuer(research_client, name="Unmapped Synthetic Inc")
    unmapped_documents = _add_documents(research_client, unmapped_issuer)
    unmapped_fact = research_client.post(
        "/v1/research/facts",
        json={
            **_fixture()["facts"][0],
            "document_id": unmapped_documents[0]["id"],
            "idempotency_key": "unmapped-synthetic-revenue",
        },
    )
    assert unmapped_fact.status_code == 201
    unmapped_run = research_client.post(
        "/v1/research/runs",
        json={
            "issuer_id": unmapped_issuer,
            "question": "Check unmapped exposure",
            "fact_ids": [unmapped_fact.json()["id"]],
            "idempotency_key": "unmapped-synthetic-run",
            "portfolio_report_id": report_id,
        },
    )
    assert unmapped_run.status_code == 201, unmapped_run.text
    assert (
        unmapped_run.json()["result"]["portfolio_context"]["status"]
        == "issuer_unmapped"
    )
    assert unmapped_run.json()["result"]["portfolio_context"]["total_exposure"] is None

    with cast(Any, research_client.app).state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ResearchRunContext)) == 3
        assert session.scalar(select(func.count()).select_from(ResearchThesisNote)) == 3
        assert (
            session.scalar(select(func.count()).select_from(ResearchWatchlistEvent))
            == 4
        )
