"""Provisional finance-side validation for attributable research passages.

This envelope is not the personal-AI wire contract. It deliberately contains no
retrieval transport, indexing, model routing, or provider implementation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

type EvidenceRejectionReason = Literal[
    "duplicate_evidence_id",
    "issuer_unattributed",
    "issuer_mismatch",
    "document_unattributed",
    "document_out_of_scope",
    "source_url_mismatch",
    "accession_mismatch",
    "publication_date_mismatch",
    "publication_date_in_future",
    "retrieval_date_unavailable",
    "retrieval_date_in_future",
    "stale",
    "content_hash_unavailable",
    "excerpt_unavailable",
    "excerpt_too_large",
    "excerpt_offset_untraceable",
    "result_item_limit_exceeded",
    "result_byte_limit_exceeded",
]


class EvidenceScopeDocument(BaseModel):
    """One manually registered source reference allowed for this request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: UUID
    issuer_id: UUID
    accession_number: str = Field(min_length=1, max_length=20)
    source_url: str = Field(min_length=1, max_length=2048)
    filing_date: date | None
    source_status: Literal["user_supplied_unverified"]


class ResearchEvidenceEligibility(BaseModel):
    """Explicit issuer, document, as-of and byte/count boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["finance-research-evidence-v1"] = (
        "finance-research-evidence-v1"
    )
    issuer_id: UUID
    allowed_documents: list[EvidenceScopeDocument] = Field(min_length=1, max_length=20)
    as_of: datetime
    max_age_days: int = Field(default=45, ge=1, le=365)
    minimum_evidence: int = Field(default=1, ge=0, le=20)
    max_items: int = Field(default=20, ge=1, le=20)
    max_excerpt_bytes: int = Field(default=4096, ge=1, le=8192)
    max_total_bytes: int = Field(default=24000, ge=1, le=48000)

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Evidence as-of timestamp must include a timezone")
        return value

    @field_validator("allowed_documents")
    @classmethod
    def scope_issuer_must_match(
        cls, documents: list[EvidenceScopeDocument], info: ValidationInfo
    ) -> list[EvidenceScopeDocument]:
        issuer_id = info.data.get("issuer_id")
        if issuer_id is not None and any(
            document.issuer_id != issuer_id for document in documents
        ):
            raise ValueError("Every allowed document must match the scoped issuer")
        if len({document.document_id for document in documents}) != len(documents):
            raise ValueError("Allowed document scope contains duplicates")
        return documents


class ResearchEvidenceCandidate(BaseModel):
    """Untrusted service candidate with source identity and excerpt coordinates."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: UUID
    issuer_id: UUID | None
    document_id: UUID | None
    accession_number: str | None = Field(default=None, max_length=20)
    source_url: str | None = Field(default=None, max_length=2048)
    published_at: date | None
    retrieved_at: datetime | None
    source_content_sha256: str | None = Field(
        default=None, pattern=r"^[a-fA-F0-9]{64}$"
    )
    excerpt: str | None = Field(default=None, max_length=8192, repr=False)
    excerpt_start_byte: int | None = Field(default=None, ge=0)
    excerpt_end_byte: int | None = Field(default=None, ge=0)
    source_length_bytes: int | None = Field(default=None, ge=0, le=20_000_000)

    @field_validator("retrieved_at")
    @classmethod
    def retrieval_date_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Evidence retrieval timestamp must include a timezone")
        return value


class EvidenceRejection(BaseModel):
    evidence_id: UUID
    reason: EvidenceRejectionReason


class ResearchEvidenceValidation(BaseModel):
    state: Literal["available", "insufficient", "conflict_present", "oversized"]
    eligible: list[ResearchEvidenceCandidate]
    rejected: list[EvidenceRejection]
    conflict_groups: list[list[UUID]]
    eligible_excerpt_bytes: int
    source_content_independently_verified: Literal[False] = False


def validate_research_evidence(
    eligibility: ResearchEvidenceEligibility,
    candidates: list[ResearchEvidenceCandidate],
) -> ResearchEvidenceValidation:
    """Keep bounded, attributable candidates and preserve conflicts explicitly.

    Matching IDs, filing metadata, URL, excerpt length, and offsets only checks
    service claims against finance's source-reference scope. It does not fetch or
    verify the source document or prove that a passage came from that document.
    """

    rejected: list[EvidenceRejection] = []
    if len(candidates) > eligibility.max_items:
        rejected.extend(
            EvidenceRejection(
                evidence_id=item.evidence_id,
                reason="result_item_limit_exceeded",
            )
            for item in candidates
        )
        return ResearchEvidenceValidation(
            state="oversized",
            eligible=[],
            rejected=rejected,
            conflict_groups=[],
            eligible_excerpt_bytes=0,
        )

    total_bytes = sum(
        len(item.excerpt.encode("utf-8")) for item in candidates if item.excerpt
    )
    if total_bytes > eligibility.max_total_bytes:
        rejected.extend(
            EvidenceRejection(
                evidence_id=item.evidence_id,
                reason="result_byte_limit_exceeded",
            )
            for item in candidates
        )
        return ResearchEvidenceValidation(
            state="oversized",
            eligible=[],
            rejected=rejected,
            conflict_groups=[],
            eligible_excerpt_bytes=0,
        )

    documents = {item.document_id: item for item in eligibility.allowed_documents}
    eligible: list[ResearchEvidenceCandidate] = []
    seen_ids: set[UUID] = set()
    for item in candidates:
        reason: EvidenceRejectionReason | None = None
        if item.evidence_id in seen_ids:
            reason = "duplicate_evidence_id"
        seen_ids.add(item.evidence_id)
        if reason is None and item.issuer_id is None:
            reason = "issuer_unattributed"
        if reason is None and item.issuer_id != eligibility.issuer_id:
            reason = "issuer_mismatch"
        document = (
            documents.get(item.document_id) if item.document_id is not None else None
        )
        if reason is None and item.document_id is None:
            reason = "document_unattributed"
        if reason is None and document is None:
            reason = "document_out_of_scope"
        if reason is None and document is not None:
            if item.source_url is None or item.source_url != document.source_url:
                reason = "source_url_mismatch"
            elif (
                item.accession_number is None
                or item.accession_number != document.accession_number
            ):
                reason = "accession_mismatch"
            elif item.published_at != document.filing_date:
                reason = "publication_date_mismatch"
        if (
            reason is None
            and item.published_at is not None
            and item.published_at > eligibility.as_of.date()
        ):
            reason = "publication_date_in_future"
        if reason is None and item.retrieved_at is None:
            reason = "retrieval_date_unavailable"
        if reason is None and item.retrieved_at is not None:
            if item.retrieved_at > eligibility.as_of:
                reason = "retrieval_date_in_future"
            elif eligibility.as_of - item.retrieved_at > timedelta(
                days=eligibility.max_age_days
            ):
                reason = "stale"
        if reason is None and item.source_content_sha256 is None:
            reason = "content_hash_unavailable"
        excerpt_bytes = len(item.excerpt.encode("utf-8")) if item.excerpt else 0
        if reason is None and (not item.excerpt or not item.excerpt.strip()):
            reason = "excerpt_unavailable"
        if reason is None and excerpt_bytes > eligibility.max_excerpt_bytes:
            reason = "excerpt_too_large"
        if reason is None and not _traceable_span(item, excerpt_bytes):
            reason = "excerpt_offset_untraceable"
        if reason is None:
            eligible.append(item)
        else:
            rejected.append(
                EvidenceRejection(evidence_id=item.evidence_id, reason=reason)
            )

    hashes_by_document: dict[UUID, dict[str, list[UUID]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in eligible:
        assert item.document_id is not None
        assert item.source_content_sha256 is not None
        hashes_by_document[item.document_id][item.source_content_sha256.lower()].append(
            item.evidence_id
        )
    conflicts = [
        [identifier for group in hash_groups.values() for identifier in group]
        for hash_groups in hashes_by_document.values()
        if len(hash_groups) > 1
    ]
    if not eligible or len(eligible) < eligibility.minimum_evidence:
        state: Literal["available", "insufficient", "conflict_present", "oversized"] = (
            "insufficient"
        )
    elif conflicts:
        state = "conflict_present"
    else:
        state = "available"
    return ResearchEvidenceValidation(
        state=state,
        eligible=eligible,
        rejected=rejected,
        conflict_groups=conflicts,
        eligible_excerpt_bytes=sum(
            len(item.excerpt.encode("utf-8")) for item in eligible if item.excerpt
        ),
    )


def _traceable_span(item: ResearchEvidenceCandidate, excerpt_bytes: int) -> bool:
    start = item.excerpt_start_byte
    end = item.excerpt_end_byte
    length = item.source_length_bytes
    return (
        start is not None
        and end is not None
        and length is not None
        and end > start
        and end - start == excerpt_bytes
        and end <= length
    )
