"""Provisional evidence-boundary validation uses invented SEC-shaped records."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from app.api.research_contracts import ResearchDocumentCreate
from app.integrations.research_evidence import (
    EvidenceScopeDocument,
    ResearchEvidenceCandidate,
    ResearchEvidenceEligibility,
    validate_research_evidence,
)


def _document() -> tuple[ResearchDocumentCreate, EvidenceScopeDocument]:
    path = (
        Path(__file__).parents[3] / "fixtures/stage-5/synthetic-company-research.json"
    )
    fixture = cast(dict[str, Any], json.loads(path.read_text()))
    issuer_id = uuid4()
    document = ResearchDocumentCreate(
        issuer_id=issuer_id,
        **fixture["documents"][0],
    )
    scope = EvidenceScopeDocument(
        document_id=uuid4(),
        issuer_id=issuer_id,
        accession_number=document.accession_number,
        source_url=document.source_url,
        filing_date=document.filing_date,
        source_status="user_supplied_unverified",
    )
    return document, scope


def _candidate(
    document: ResearchDocumentCreate,
    scope: EvidenceScopeDocument,
    *,
    evidence_id: UUID | None = None,
    issuer_id: UUID | None = None,
    document_id: UUID | None = None,
    accession_number: str | None = None,
    source_url: str | None = None,
    published_at: datetime | None = None,
    retrieved_at: datetime | None = None,
    content_hash: str = "a" * 64,
    excerpt: str = "Synthetic revenue was reported as $100 million.",
    excerpt_start: int = 120,
    excerpt_end: int | None = None,
    source_length: int = 1000,
) -> ResearchEvidenceCandidate:
    excerpt_size = len(excerpt.encode("utf-8"))
    return ResearchEvidenceCandidate(
        evidence_id=evidence_id or uuid4(),
        issuer_id=issuer_id if issuer_id is not None else document.issuer_id,
        document_id=document_id if document_id is not None else scope.document_id,
        accession_number=(
            accession_number
            if accession_number is not None
            else document.accession_number
        ),
        source_url=source_url if source_url is not None else document.source_url,
        published_at=published_at if published_at is not None else document.filing_date,
        retrieved_at=(
            retrieved_at
            if retrieved_at is not None
            else datetime(2026, 10, 3, tzinfo=UTC)
        ),
        source_content_sha256=content_hash,
        excerpt=excerpt,
        excerpt_start_byte=excerpt_start,
        excerpt_end_byte=(
            excerpt_end if excerpt_end is not None else excerpt_start + excerpt_size
        ),
        source_length_bytes=source_length,
    )


def _eligibility(
    document: ResearchDocumentCreate,
    scope: EvidenceScopeDocument,
    **overrides: Any,
) -> ResearchEvidenceEligibility:
    values: dict[str, Any] = {
        "issuer_id": document.issuer_id,
        "allowed_documents": [scope],
        "as_of": datetime(2026, 10, 3, tzinfo=UTC),
        **overrides,
    }
    return ResearchEvidenceEligibility.model_validate(values)


def test_evidence_validation_checks_identity_freshness_and_traceable_bounds() -> None:
    document, scope = _document()
    eligible = _candidate(document, scope)
    stale = _candidate(
        document,
        scope,
        evidence_id=uuid4(),
        retrieved_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    wrong_issuer = _candidate(document, scope, evidence_id=uuid4(), issuer_id=uuid4())
    out_of_scope = _candidate(document, scope, evidence_id=uuid4(), document_id=uuid4())
    nontraceable = _candidate(
        document,
        scope,
        evidence_id=uuid4(),
        excerpt_end=125,
    )
    missing_identity = _candidate(document, scope, evidence_id=uuid4()).model_copy(
        update={"issuer_id": None, "document_id": None}
    )
    result = validate_research_evidence(
        _eligibility(document, scope),
        [eligible, stale, wrong_issuer, out_of_scope, nontraceable, missing_identity],
    )

    assert result.state == "available"
    assert result.eligible == [eligible]
    assert result.source_content_independently_verified is False
    assert {item.reason for item in result.rejected} == {
        "stale",
        "issuer_mismatch",
        "document_out_of_scope",
        "excerpt_offset_untraceable",
        "issuer_unattributed",
    }


def test_evidence_conflicts_are_preserved_and_insufficient_is_explicit() -> None:
    document, scope = _document()
    first = _candidate(document, scope, content_hash="a" * 64)
    second = _candidate(document, scope, content_hash="b" * 64)
    conflicted = validate_research_evidence(
        _eligibility(document, scope), [first, second]
    )
    assert conflicted.state == "conflict_present"
    assert len(conflicted.eligible) == 2
    assert len(conflicted.conflict_groups) == 1

    stale = _candidate(
        document,
        scope,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    insufficient = validate_research_evidence(_eligibility(document, scope), [stale])
    assert insufficient.state == "insufficient"
    assert insufficient.eligible == []


def test_evidence_byte_item_and_excerpt_limits_reject_without_truncation() -> None:
    document, scope = _document()
    candidate = _candidate(document, scope, excerpt="abcdef")
    byte_overflow = validate_research_evidence(
        _eligibility(document, scope, max_total_bytes=5), [candidate]
    )
    assert byte_overflow.state == "oversized"
    assert byte_overflow.rejected[0].reason == "result_byte_limit_exceeded"
    assert byte_overflow.eligible == []

    too_many = validate_research_evidence(
        _eligibility(document, scope, max_items=1),
        [candidate, _candidate(document, scope)],
    )
    assert too_many.state == "oversized"
    assert {item.reason for item in too_many.rejected} == {"result_item_limit_exceeded"}

    excerpt_overflow = validate_research_evidence(
        _eligibility(document, scope, max_excerpt_bytes=5), [candidate]
    )
    assert excerpt_overflow.state == "insufficient"
    assert excerpt_overflow.rejected[0].reason == "excerpt_too_large"


def test_scope_and_retrieval_dates_require_timezone_and_same_issuer() -> None:
    document, scope = _document()
    try:
        _eligibility(document, scope, as_of=datetime(2026, 10, 3))
        raise AssertionError("naive as-of timestamps must fail")
    except ValueError as exc:
        assert "timezone" in str(exc)

    try:
        ResearchEvidenceEligibility(
            issuer_id=uuid4(),
            allowed_documents=[scope],
            as_of=datetime(2026, 10, 3, tzinfo=UTC),
        )
        raise AssertionError("cross-issuer document scope must fail")
    except ValueError as exc:
        assert "scoped issuer" in str(exc)

    try:
        _candidate(
            document,
            scope,
            retrieved_at=datetime(2026, 10, 3),
        )
        raise AssertionError("naive retrieval timestamps must fail")
    except ValueError as exc:
        assert "timezone" in str(exc)


def test_freshness_uses_elapsed_time_and_empty_sources_are_insufficient() -> None:
    document, scope = _document()
    policy = _eligibility(document, scope)
    exact_boundary = _candidate(
        document, scope, retrieved_at=policy.as_of - timedelta(days=45)
    )
    just_stale = _candidate(
        document,
        scope,
        retrieved_at=policy.as_of - timedelta(days=45, seconds=1),
    )
    result = validate_research_evidence(policy, [exact_boundary, just_stale])
    assert result.eligible == [exact_boundary]
    assert result.rejected[0].reason == "stale"
    assert (
        validate_research_evidence(
            _eligibility(document, scope, minimum_evidence=0), []
        ).state
        == "insufficient"
    )

    blank = validate_research_evidence(
        policy, [_candidate(document, scope, excerpt=" ")]
    )
    assert blank.state == "insufficient"
    assert blank.rejected[0].reason == "excerpt_unavailable"


def test_scoped_future_filing_is_ineligible_for_historical_research() -> None:
    document, scope = _document()
    as_of = datetime(2026, 10, 3, tzinfo=UTC)
    future_date = (as_of + timedelta(days=1)).date()
    future_scope = scope.model_copy(update={"filing_date": future_date})
    future_candidate = _candidate(document, scope).model_copy(
        update={"published_at": future_date}
    )
    result = validate_research_evidence(
        _eligibility(document, future_scope), [future_candidate]
    )
    assert result.state == "insufficient"
    assert result.rejected[0].reason == "publication_date_in_future"
