"""Finance-owned storage and checks for manually registered research evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.contracts import IssuerRead
from app.api.research_contracts import (
    FactComparisonCreate,
    ReportedFactCreate,
    ReportedFactRead,
    ResearchBaselineSnapshot,
    ResearchCitationRead,
    ResearchCompanyRead,
    ResearchDocumentCreate,
    ResearchDocumentRead,
    ResearchFactObservation,
    ResearchRunCreate,
    ResearchRunRead,
)
from app.db.models import (
    Issuer,
    ReportedFact,
    ResearchDocument,
    ResearchResult,
    ResearchRun,
    utc_now,
)


class ResearchNotFound(LookupError):
    """A requested finance research record does not exist."""


class ResearchConflict(ValueError):
    """An idempotency or immutable filing identity was reused with other data."""


def _fingerprint(data: Mapping[str, object]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _wire_value(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f") if value else "0"
    return value


def create_document(
    session: Session, data: ResearchDocumentCreate
) -> tuple[ResearchDocument, bool]:
    if session.get(Issuer, data.issuer_id) is None:
        raise ResearchNotFound("Issuer not found")
    existing = session.scalar(
        select(ResearchDocument).where(
            ResearchDocument.issuer_id == data.issuer_id,
            ResearchDocument.accession_number == data.accession_number,
        )
    )
    if existing is not None:
        proposed = data.model_dump(mode="json")
        current = {key: _wire_value(getattr(existing, key)) for key in proposed}
        if _fingerprint(proposed) != _fingerprint(current):
            raise ResearchConflict(
                "Accession is already registered with other metadata"
            )
        return existing, True

    record = ResearchDocument(
        id=uuid4(),
        issuer_id=data.issuer_id,
        cik=data.cik,
        accession_number=data.accession_number,
        form_type=data.form_type,
        title=data.title,
        source_url=data.source_url,
        filing_date=data.filing_date,
        period_start=data.period_start,
        period_end=data.period_end,
        recorded_at=utc_now(),
        source_status="user_supplied_unverified",
    )
    session.add(record)
    session.flush()
    return record, False


def create_fact(
    session: Session, data: ReportedFactCreate
) -> tuple[ReportedFact, bool]:
    document = session.get(ResearchDocument, data.document_id)
    if document is None:
        raise ResearchNotFound("Research document not found")
    existing = session.scalar(
        select(ReportedFact).where(ReportedFact.idempotency_key == data.idempotency_key)
    )
    if existing is not None:
        proposed = data.model_dump(mode="json")
        if data.normalized_value is not None:
            proposed["normalized_value"] = format(
                Decimal(data.normalized_value).normalize(), "f"
            )
        current = {key: _wire_value(getattr(existing, key)) for key in proposed}
        if _fingerprint(proposed) != _fingerprint(current):
            raise ResearchConflict("Idempotency key is already used with other data")
        return existing, True

    record = ReportedFact(
        id=uuid4(),
        document_id=data.document_id,
        taxonomy=data.taxonomy,
        concept=data.concept,
        raw_value=data.raw_value,
        normalized_value=(
            Decimal(data.normalized_value)
            if data.normalized_value is not None
            else None
        ),
        unit=data.unit,
        currency=data.currency,
        period_kind=data.period_kind,
        period_start=data.period_start,
        period_end=data.period_end,
        instant=data.instant,
        fiscal_year=data.fiscal_year,
        fiscal_period=data.fiscal_period,
        context_ref=data.context_ref,
        quality_status="user_supplied_unverified",
        idempotency_key=data.idempotency_key,
        created_at=utc_now(),
    )
    session.add(record)
    session.flush()
    return record, False


def documents_for_issuer(session: Session, issuer_id: UUID) -> list[ResearchDocument]:
    return list(
        session.scalars(
            select(ResearchDocument)
            .where(ResearchDocument.issuer_id == issuer_id)
            .order_by(ResearchDocument.filing_date.desc(), ResearchDocument.id)
            .limit(100)
        )
    )


def facts_for_documents(
    session: Session, document_ids: list[UUID]
) -> list[ReportedFact]:
    if not document_ids:
        return []
    return list(
        session.scalars(
            select(ReportedFact)
            .where(ReportedFact.document_id.in_(document_ids))
            .order_by(ReportedFact.concept, ReportedFact.fiscal_year, ReportedFact.id)
            .limit(500)
        )
    )


def issuer_exists(session: Session, issuer_id: UUID) -> bool:
    return session.get(Issuer, issuer_id) is not None


def document_exists(session: Session, document_id: UUID) -> bool:
    return session.get(ResearchDocument, document_id) is not None


def company_research(session: Session, issuer_id: UUID) -> ResearchCompanyRead:
    issuer = session.get(Issuer, issuer_id)
    if issuer is None:
        raise ResearchNotFound("Issuer not found")
    documents = documents_for_issuer(session, issuer_id)
    facts = facts_for_documents(session, [row.id for row in documents])
    document_by_id = {row.id: row for row in documents}
    return ResearchCompanyRead(
        issuer=IssuerRead(id=issuer.id, display_name=issuer.display_name),
        documents=[ResearchDocumentRead.model_validate(row) for row in documents],
        facts=[
            ResearchFactObservation(
                fact=ReportedFactRead.model_validate(row),
                document=ResearchDocumentRead.model_validate(
                    document_by_id[row.document_id]
                ),
            )
            for row in facts
            if row.document_id in document_by_id
        ],
    )


def compare_facts(session: Session, data: FactComparisonCreate) -> dict[str, object]:
    prior = session.get(ReportedFact, data.prior_fact_id)
    current = session.get(ReportedFact, data.current_fact_id)
    if prior is None or current is None:
        raise ResearchNotFound("Reported fact not found")
    prior_document = session.get(ResearchDocument, prior.document_id)
    current_document = session.get(ResearchDocument, current.document_id)
    if prior_document is None or current_document is None:
        raise ResearchNotFound("Research document not found")

    diagnostics: list[str] = []
    comparable = True
    comparison_fields = (
        (prior_document.issuer_id == current_document.issuer_id, "issuer_mismatch"),
        (prior.taxonomy == current.taxonomy, "taxonomy_mismatch"),
        (prior.concept == current.concept, "concept_mismatch"),
        (prior.unit == current.unit, "unit_mismatch"),
        (prior.currency == current.currency, "currency_mismatch"),
        (prior.period_kind == current.period_kind, "period_kind_mismatch"),
        (prior.fiscal_period == current.fiscal_period, "fiscal_period_mismatch"),
        (
            prior.fiscal_year is not None
            and current.fiscal_year == prior.fiscal_year + 1,
            "not_consecutive_fiscal_years",
        ),
        (
            prior.normalized_value is not None and current.normalized_value is not None,
            "normalized_value_missing",
        ),
    )
    for condition, diagnostic in comparison_fields:
        if not condition:
            diagnostics.append(diagnostic)
            comparable = False

    if comparable and prior.period_kind == "duration":
        if not all(
            (
                prior.period_start,
                prior.period_end,
                current.period_start,
                current.period_end,
            )
        ):
            comparable = False
            diagnostics.append("duration_dates_missing")
        else:
            assert prior.period_start and prior.period_end
            assert current.period_start and current.period_end
            prior_days = (prior.period_end - prior.period_start).days
            current_days = (current.period_end - current.period_start).days
            end_gap = (current.period_end - prior.period_end).days
            if abs(prior_days - current_days) > 3 or not 350 <= end_gap <= 380:
                comparable = False
                diagnostics.append("duration_window_mismatch")
    elif comparable:
        if prior.instant is None or current.instant is None:
            comparable = False
            diagnostics.append("instant_date_missing")
        elif not 350 <= (current.instant - prior.instant).days <= 380:
            comparable = False
            diagnostics.append("instant_window_mismatch")

    absolute_change: Decimal | None = None
    percent_change: Decimal | None = None
    if comparable:
        assert prior.normalized_value is not None
        assert current.normalized_value is not None
        with localcontext() as context:
            context.prec = 80
            absolute_change = current.normalized_value - prior.normalized_value
            if prior.normalized_value > 0:
                percent_change = absolute_change / prior.normalized_value * Decimal(100)
            else:
                diagnostics.append("percent_change_unavailable_nonpositive_baseline")

    return {
        "status": "comparable" if comparable else "unavailable",
        "methodology_version": "same-fiscal-period-yoy-v1",
        "prior": ResearchFactObservation(
            fact=ReportedFactRead.model_validate(prior),
            document=ResearchDocumentRead.model_validate(prior_document),
        ),
        "current": ResearchFactObservation(
            fact=ReportedFactRead.model_validate(current),
            document=ResearchDocumentRead.model_validate(current_document),
        ),
        "absolute_change": _decimal_string(absolute_change),
        "percent_change": _decimal_string(percent_change),
        "diagnostics": diagnostics,
    }


def _decimal_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f") if value else "0"


def _result_bytes(snapshot: dict[str, object]) -> bytes:
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()


def create_baseline_run(
    session: Session, data: ResearchRunCreate
) -> tuple[ResearchRun, ResearchResult, bool]:
    issuer = session.get(Issuer, data.issuer_id)
    if issuer is None:
        raise ResearchNotFound("Issuer not found")
    fingerprint_data = {
        "issuer_id": str(data.issuer_id),
        "question": data.question,
        "fact_ids": [str(identifier) for identifier in data.fact_ids],
        "schema_version": "finance-research-baseline-v1",
    }
    fingerprint = _fingerprint(fingerprint_data)
    existing = session.scalar(
        select(ResearchRun).where(ResearchRun.idempotency_key == data.idempotency_key)
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ResearchConflict(
                "Run idempotency key is already used with other data"
            )
        result = session.scalar(
            select(ResearchResult).where(ResearchResult.run_id == existing.id)
        )
        existing_hash = (
            hashlib.sha256(_result_bytes(result.result_snapshot)).hexdigest()
            if result is not None
            else None
        )
        if result is None or existing_hash != result.result_hash:
            raise ResearchNotFound("Frozen research result is unavailable")
        return existing, result, True

    rows = list(
        session.execute(
            select(ReportedFact, ResearchDocument)
            .join(ResearchDocument, ResearchDocument.id == ReportedFact.document_id)
            .where(ReportedFact.id.in_(data.fact_ids))
        )
    )
    row_by_id = {fact.id: (fact, document) for fact, document in rows}
    if set(row_by_id) != set(data.fact_ids):
        raise ResearchNotFound("One or more selected facts are unavailable")
    if any(document.issuer_id != data.issuer_id for _fact, document in rows):
        raise ResearchConflict("Selected facts must belong to the requested issuer")

    now = utc_now()
    observations = [
        ResearchFactObservation(
            fact=ReportedFactRead.model_validate(row_by_id[identifier][0]),
            document=ResearchDocumentRead.model_validate(row_by_id[identifier][1]),
        )
        for identifier in data.fact_ids
    ]
    citations = [
        ResearchCitationRead(
            fact_id=item.fact.id,
            document_id=item.document.id,
            accession_number=item.document.accession_number,
            form_type=item.document.form_type,
            source_url=item.document.source_url,
            title=item.document.title,
            filing_date=item.document.filing_date,
            quality_status="user_supplied_unverified",
        )
        for item in observations
    ]
    snapshot_model = ResearchBaselineSnapshot(
        schema_version="finance-research-baseline-v1",
        issuer_id=issuer.id,
        issuer_name=issuer.display_name,
        question=data.question,
        generated_at=now,
        mode="offline_deterministic",
        facts=observations,
        citations=citations,
        inferences=[],
        unknowns=[
            "No shared research service or model synthesis was run.",
            "Entered source values are unverified and may be incomplete or amended.",
        ],
    )
    snapshot = snapshot_model.model_dump(mode="json")
    encoded = _result_bytes(snapshot)
    if len(encoded) > 128_000:
        raise ResearchConflict("Selected research result exceeds the 128 KB limit")

    run = ResearchRun(
        id=uuid4(),
        issuer_id=issuer.id,
        idempotency_key=data.idempotency_key,
        request_fingerprint=fingerprint,
        question=data.question,
        selected_fact_ids=[str(identifier) for identifier in data.fact_ids],
        state="completed",
        created_at=now,
    )
    result = ResearchResult(
        id=uuid4(),
        run_id=run.id,
        schema_version="finance-research-baseline-v1",
        validation_status="source_links_checked_unverified_values",
        result_hash=hashlib.sha256(encoded).hexdigest(),
        result_snapshot=snapshot,
        generated_at=now,
    )
    session.add_all([run, result])
    session.flush()
    return run, result, False


def research_run(session: Session, run_id: UUID) -> tuple[ResearchRun, ResearchResult]:
    run = session.get(ResearchRun, run_id)
    if run is None:
        raise ResearchNotFound("Research run not found")
    result = session.scalar(
        select(ResearchResult).where(ResearchResult.run_id == run.id)
    )
    if (
        result is None
        or hashlib.sha256(_result_bytes(result.result_snapshot)).hexdigest()
        != result.result_hash
    ):
        raise ResearchNotFound("Frozen research result is unavailable")
    return run, result


def read_run(
    session: Session, run_id: UUID, *, duplicate: bool = False
) -> ResearchRunRead:
    run, result = research_run(session, run_id)
    return ResearchRunRead(
        id=run.id,
        issuer_id=run.issuer_id,
        idempotency_key=run.idempotency_key,
        request_fingerprint=run.request_fingerprint,
        question=run.question,
        selected_fact_ids=[UUID(identifier) for identifier in run.selected_fact_ids],
        state="completed",
        created_at=run.created_at,
        schema_version="finance-research-baseline-v1",
        validation_status="source_links_checked_unverified_values",
        result_hash=result.result_hash,
        result=ResearchBaselineSnapshot.model_validate(result.result_snapshot),
        duplicate=duplicate,
    )
