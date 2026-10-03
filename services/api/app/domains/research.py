"""Finance-owned storage and checks for manually registered research evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
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
    ResearchPortfolioContext,
    ResearchPortfolioContribution,
    ResearchRunCreate,
    ResearchRunRead,
    ResearchThesisNoteCreate,
    ResearchThesisNoteRead,
    ResearchWatchlistEventCreate,
    ResearchWatchlistRead,
)
from app.db.models import (
    Issuer,
    ReportedFact,
    ResearchDocument,
    ResearchResult,
    ResearchRun,
    ResearchRunContext,
    ResearchThesisNote,
    ResearchWatchlistEvent,
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


def thesis_notes_for_issuer(
    session: Session, issuer_id: UUID
) -> list[ResearchThesisNote]:
    return list(
        session.scalars(
            select(ResearchThesisNote)
            .where(ResearchThesisNote.issuer_id == issuer_id)
            .order_by(ResearchThesisNote.version.desc())
            .limit(100)
        )
    )


def create_thesis_note(
    session: Session, data: ResearchThesisNoteCreate
) -> tuple[ResearchThesisNote, bool]:
    if session.get(Issuer, data.issuer_id) is None:
        raise ResearchNotFound("Issuer not found")
    existing = session.scalar(
        select(ResearchThesisNote).where(
            ResearchThesisNote.issuer_id == data.issuer_id,
            ResearchThesisNote.idempotency_key == data.idempotency_key,
        )
    )
    if existing is not None:
        if existing.text != data.text:
            raise ResearchConflict("Thesis note key is already used with other text")
        return existing, True
    latest_version = session.scalar(
        select(func.max(ResearchThesisNote.version)).where(
            ResearchThesisNote.issuer_id == data.issuer_id
        )
    )
    record = ResearchThesisNote(
        id=uuid4(),
        issuer_id=data.issuer_id,
        version=(latest_version or 0) + 1,
        text=data.text,
        idempotency_key=data.idempotency_key,
        created_at=utc_now(),
    )
    session.add(record)
    session.flush()
    return record, False


def thesis_note_for_run(
    session: Session, note_id: UUID | None, issuer_id: UUID
) -> ResearchThesisNoteRead | None:
    if note_id is None:
        return None
    record = session.get(ResearchThesisNote, note_id)
    if record is None or record.issuer_id != issuer_id:
        raise ResearchNotFound("Thesis note for this issuer was not found")
    return ResearchThesisNoteRead.model_validate(record)


def latest_watchlist_event(
    session: Session, issuer_id: UUID
) -> ResearchWatchlistEvent | None:
    return session.scalar(
        select(ResearchWatchlistEvent)
        .where(ResearchWatchlistEvent.issuer_id == issuer_id)
        .order_by(ResearchWatchlistEvent.version.desc())
        .limit(1)
    )


def watchlist_state(session: Session, issuer_id: UUID) -> ResearchWatchlistRead:
    issuer = session.get(Issuer, issuer_id)
    if issuer is None:
        raise ResearchNotFound("Issuer not found")
    event = latest_watchlist_event(session, issuer_id)
    return ResearchWatchlistRead(
        issuer_id=issuer.id,
        issuer_name=issuer.display_name,
        version=event.version if event is not None else None,
        active=event.action == "added" if event is not None else False,
        changed_at=event.created_at if event is not None else None,
    )


def active_watchlist(session: Session) -> list[ResearchWatchlistRead]:
    latest_versions = (
        select(
            ResearchWatchlistEvent.issuer_id.label("issuer_id"),
            func.max(ResearchWatchlistEvent.version).label("version"),
        )
        .group_by(ResearchWatchlistEvent.issuer_id)
        .subquery()
    )
    rows = list(
        session.execute(
            select(ResearchWatchlistEvent, Issuer)
            .join(
                latest_versions,
                and_(
                    latest_versions.c.issuer_id == ResearchWatchlistEvent.issuer_id,
                    latest_versions.c.version == ResearchWatchlistEvent.version,
                ),
            )
            .join(Issuer, Issuer.id == ResearchWatchlistEvent.issuer_id)
            .order_by(Issuer.display_name, Issuer.id)
            .limit(500)
        )
    )
    return [
        ResearchWatchlistRead(
            issuer_id=issuer.id,
            issuer_name=issuer.display_name,
            version=event.version,
            active=True,
            changed_at=event.created_at,
        )
        for event, issuer in rows
        if event.action == "added"
    ]


def change_watchlist(
    session: Session, issuer_id: UUID, data: ResearchWatchlistEventCreate
) -> tuple[ResearchWatchlistEvent, bool]:
    if session.get(Issuer, issuer_id) is None:
        raise ResearchNotFound("Issuer not found")
    existing = session.scalar(
        select(ResearchWatchlistEvent).where(
            ResearchWatchlistEvent.issuer_id == issuer_id,
            ResearchWatchlistEvent.idempotency_key == data.idempotency_key,
        )
    )
    if existing is not None:
        if existing.action != data.action:
            raise ResearchConflict("Watchlist key is already used for another action")
        return existing, True
    latest = latest_watchlist_event(session, issuer_id)
    record = ResearchWatchlistEvent(
        id=uuid4(),
        issuer_id=issuer_id,
        version=(latest.version if latest is not None else 0) + 1,
        action=data.action,
        idempotency_key=data.idempotency_key,
        created_at=utc_now(),
    )
    session.add(record)
    session.flush()
    return record, False


def _optional_uuid(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def portfolio_context_from_report(
    report: dict[str, Any], *, issuer_id: UUID, issuer_name: str
) -> ResearchPortfolioContext:
    if report.get("reconciled") is not True:
        raise ResearchConflict("Selected portfolio report does not reconcile")
    matching = next(
        (
            row
            for row in report.get("issuer_rows", [])
            if row.get("id") == str(issuer_id)
        ),
        None,
    )
    common: dict[str, Any] = {
        "report_id": UUID(report["id"]),
        "report_input_hash": str(report["input_hash"]),
        "report_generated_at": report["generated_at"],
        "valuation_at": report["valuation_at"],
        "account_ids": [UUID(value) for value in report.get("account_ids", [])],
        "nav_status": report["nav_status"],
        "issuer_id": issuer_id,
        "issuer_name": issuer_name,
        "reconciled": True,
        "warnings": list(report.get("warnings", [])),
    }
    if matching is None:
        return ResearchPortfolioContext(
            status="issuer_unmapped",
            direct_exposure=None,
            indirect_exposure=None,
            total_exposure=None,
            contributions=[],
            warnings=[
                *common["warnings"],
                "No direct or ETF-derived exposure maps to this issuer in the report.",
            ],
            **{key: value for key, value in common.items() if key != "warnings"},
        )

    source_rows = matching.get("contributions", [])
    if len(source_rows) > 100:
        raise ResearchConflict(
            "Selected issuer has over 100 source contributions; "
            "create a narrower report"
        )
    contributions = [
        ResearchPortfolioContribution(
            account_id=UUID(str(row["account_id"])),
            account_name=str(row["account_name"]),
            exposure_kind=row["category"],
            amount=str(row["amount"]),
            security_id=UUID(str(row["security_id"])),
            position_id=UUID(str(row["position_id"])),
            position_snapshot_id=UUID(str(row["position_snapshot_id"])),
            position_as_of=row["position_as_of"],
            position_source=str(row["position_source"]),
            position_quality=str(row["position_quality"]),
            quote_id=_optional_uuid(row.get("quote_id")),
            quote_as_of=row.get("quote_as_of"),
            quote_source=row.get("quote_source"),
            quality_status=str(row["quality_status"]),
            fund_snapshot_id=_optional_uuid(row.get("fund_snapshot_id")),
            fund_as_of=row.get("fund_as_of"),
            fund_fetched_at=row.get("fund_fetched_at"),
            fund_source=row.get("fund_source"),
            fund_source_url=row.get("fund_source_url"),
            fund_quality=row.get("fund_quality"),
            fund_stale=bool(row.get("fund_stale", False)),
        )
        for row in source_rows
    ]
    direct = Decimal(str(matching["direct"]))
    indirect = Decimal(str(matching["indirect"]))
    total = Decimal(str(matching["total"]))
    contribution_direct = sum(
        (Decimal(row.amount) for row in contributions if row.exposure_kind == "direct"),
        Decimal(0),
    )
    contribution_indirect = sum(
        (
            Decimal(row.amount)
            for row in contributions
            if row.exposure_kind == "indirect"
        ),
        Decimal(0),
    )
    if (
        direct + indirect != total
        or contribution_direct != direct
        or contribution_indirect != indirect
    ):
        raise ResearchConflict("Issuer contributions do not reconcile to the report")
    return ResearchPortfolioContext(
        status="matched",
        direct_exposure=_decimal_string(direct),
        indirect_exposure=_decimal_string(indirect),
        total_exposure=_decimal_string(total),
        contributions=contributions,
        **common,
    )


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
    session: Session,
    data: ResearchRunCreate,
    *,
    portfolio_context: ResearchPortfolioContext | None = None,
    thesis_note: ResearchThesisNoteRead | None = None,
) -> tuple[ResearchRun, ResearchResult, bool]:
    issuer = session.get(Issuer, data.issuer_id)
    if issuer is None:
        raise ResearchNotFound("Issuer not found")
    if (data.portfolio_report_id is None) != (portfolio_context is None):
        raise ResearchConflict("Portfolio report context is missing or unexpected")
    if (
        portfolio_context is not None
        and portfolio_context.report_id != data.portfolio_report_id
    ):
        raise ResearchConflict("Portfolio context does not match the selected report")
    if (data.thesis_note_id is None) != (thesis_note is None):
        raise ResearchConflict("Thesis note snapshot is missing or unexpected")
    if thesis_note is not None and (
        thesis_note.id != data.thesis_note_id or thesis_note.issuer_id != data.issuer_id
    ):
        raise ResearchConflict("Thesis note does not match the selected issuer")
    fingerprint_data = {
        "issuer_id": str(data.issuer_id),
        "question": data.question,
        "fact_ids": [str(identifier) for identifier in data.fact_ids],
        "portfolio_report_id": (
            str(data.portfolio_report_id) if data.portfolio_report_id else None
        ),
        "portfolio_report_input_hash": (
            portfolio_context.report_input_hash if portfolio_context else None
        ),
        "thesis_note_id": str(data.thesis_note_id) if data.thesis_note_id else None,
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
        portfolio_context=portfolio_context,
        thesis_note=thesis_note,
        inferences=[],
        unknowns=[
            "No shared research service or model synthesis was run.",
            "Entered source values are unverified and may be incomplete or amended.",
            *(
                ["Selected portfolio report has no mapped issuer exposure."]
                if portfolio_context is not None
                and portfolio_context.status == "issuer_unmapped"
                else []
            ),
            *(
                ["No portfolio report was selected; ownership context is unavailable."]
                if portfolio_context is None
                else []
            ),
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
    records = [run, result]
    if portfolio_context is not None or thesis_note is not None:
        records.append(
            ResearchRunContext(
                id=uuid4(),
                run_id=run.id,
                portfolio_report_id=(
                    portfolio_context.report_id if portfolio_context else None
                ),
                thesis_note_id=thesis_note.id if thesis_note else None,
            )
        )
    session.add_all(records)
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
