"""Finance-owned storage and checks for manually registered research evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.research_contracts import ReportedFactCreate, ResearchDocumentCreate
from app.db.models import Issuer, ReportedFact, ResearchDocument, utc_now


class ResearchNotFound(LookupError):
    """A requested finance research record does not exist."""


class ResearchConflict(ValueError):
    """An idempotency or immutable filing identity was reused with other data."""


def _fingerprint(data: dict[str, object]) -> str:
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


def documents_for_issuer(session: Session, issuer_id):
    return list(
        session.scalars(
            select(ResearchDocument)
            .where(ResearchDocument.issuer_id == issuer_id)
            .order_by(ResearchDocument.filing_date.desc(), ResearchDocument.id)
            .limit(100)
        )
    )


def facts_for_documents(session: Session, document_ids: list):
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


def issuer_exists(session: Session, issuer_id) -> bool:
    return session.get(Issuer, issuer_id) is not None


def document_exists(session: Session, document_id) -> bool:
    return session.get(ResearchDocument, document_id) is not None
