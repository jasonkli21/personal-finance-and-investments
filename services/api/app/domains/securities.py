"""Reviewed local security/issuer catalog and bounded search."""

from datetime import date
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.contracts import SecurityCreate
from app.db.models import (
    Issuer,
    IssuerMappingEvent,
    Security,
    SecurityIdentifier,
    utc_now,
)


def resolve_securities(session: Session, query: str) -> list[Security]:
    normalized = query.strip()
    if len(normalized) < 2:
        return []
    ticker_prefix = normalized.upper().replace("%", "\\%").replace("_", "\\_")
    name_pattern = normalized.replace("%", "\\%").replace("_", "\\_")
    statement = (
        select(Security)
        .where(
            Security.display_ticker.like(f"{ticker_prefix}%", escape="\\")
            | func.lower(Security.name).like(f"%{name_pattern.lower()}%", escape="\\")
        )
        .order_by(Security.display_ticker, Security.name, Security.id)
        .limit(11)
    )
    return list(session.scalars(statement))


class CatalogConflict(ValueError):
    """A reviewed catalog identity already exists."""


class CatalogNotFound(ValueError):
    """A requested security or issuer does not exist."""


class CatalogRevisionConflict(CatalogConflict):
    """The reviewed issuer mapping changed before this write."""


def create_issuer(session: Session, display_name: str) -> Issuer:
    normalized = " ".join(display_name.casefold().split())
    existing = session.scalar(
        select(Issuer).where(Issuer.normalized_name == normalized)
    )
    if existing is not None:
        raise CatalogConflict("An issuer with this normalized name already exists.")
    issuer = Issuer(
        id=uuid4(), normalized_name=normalized, display_name=display_name.strip()
    )
    session.add(issuer)
    session.flush()
    return issuer


def create_security(session: Session, data: SecurityCreate) -> Security:
    if data.issuer_id is not None and session.get(Issuer, data.issuer_id) is None:
        raise CatalogNotFound("Issuer not found.")
    ticker = data.display_ticker.strip().upper() if data.display_ticker else None
    if ticker and session.scalar(
        select(Security.id).where(Security.display_ticker == ticker)
    ):
        raise CatalogConflict("A security with this ticker already exists.")
    security = Security(
        id=uuid4(),
        security_type=data.security_type,
        display_ticker=ticker,
        name=data.name.strip(),
        issuer_id=data.issuer_id,
        currency=data.currency,
    )
    session.add(security)
    session.flush()
    if data.issuer_id is not None:
        session.add(
            IssuerMappingEvent(
                id=uuid4(),
                security_id=security.id,
                previous_issuer_id=None,
                new_issuer_id=data.issuer_id,
                reason="Reviewed during local catalog creation",
            )
        )
    if data.identifier_namespace and data.identifier_value:
        value = data.identifier_value.strip()
        session.add(
            SecurityIdentifier(
                id=uuid4(),
                security_id=security.id,
                namespace=data.identifier_namespace.strip().casefold(),
                exchange=data.identifier_exchange.strip().upper(),
                value=value,
                normalized_value=value.upper(),
                valid_from=date.today(),
                valid_to=None,
                source="manual_review",
                review_status="reviewed",
            )
        )
    session.flush()
    return security


def assign_issuer(
    session: Session,
    security_id: UUID,
    issuer_id: UUID | None,
    expected_issuer_id: UUID | None,
    reason: str,
) -> Security:
    security = session.get(Security, security_id)
    if security is None:
        raise CatalogNotFound
    if security.issuer_id != expected_issuer_id:
        raise CatalogRevisionConflict
    if issuer_id is not None and session.get(Issuer, issuer_id) is None:
        raise CatalogNotFound("Issuer not found.")
    previous = security.issuer_id
    moved = session.execute(
        update(Security)
        .where(
            Security.id == security_id,
            Security.issuer_id == expected_issuer_id
            if expected_issuer_id is not None
            else Security.issuer_id.is_(None),
        )
        .values(issuer_id=issuer_id)
        .execution_options(synchronize_session=False)
    )
    if getattr(moved, "rowcount", 0) != 1:
        raise CatalogRevisionConflict
    security.issuer_id = issuer_id
    session.add(
        IssuerMappingEvent(
            id=uuid4(),
            security_id=security_id,
            previous_issuer_id=previous,
            new_issuer_id=issuer_id,
            reason=reason.strip(),
            changed_at=utc_now(),
        )
    )
    session.flush()
    return security
