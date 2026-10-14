"""Bounded read projections for the Finance-owned Personal AI contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    AccountBalanceObservation,
    Issuer,
    MonthlyDiscretionaryBudget,
    PositionSnapshot,
    PositionSnapshotLine,
    ReportedFact,
    ResearchDocument,
    ResearchThesisNote,
    Security,
)
from app.integrations.finance_context import (
    FinanceContextAuthority,
    FinanceContextEntityReference,
    FinanceContextFieldSensitivity,
    FinanceContextPermissionDependency,
    FinanceContextReadRequest,
    FinanceContextReadResponse,
    FinanceContextRecord,
    FinanceContextRecordEntityType,
    FinanceContextSourceClass,
    FinanceContextSourceReference,
    FinanceSemanticClass,
    FinanceSemanticState,
    FinanceSemanticValue,
)


class FinanceContextNotFound(LookupError):
    """An explicitly selected Finance entity is unavailable to this principal."""


class FinanceContextSelectionError(ValueError):
    """The requested data cannot be represented within the narrow read contract."""


def read_finance_context(
    session: Session,
    request: FinanceContextReadRequest,
    *,
    principal_scope_id: str,
) -> FinanceContextReadResponse:
    """Project only selected current records from Finance's canonical database.

    Finance currently has one explicitly bound personal scope per database. That
    binding is verified by the API before this function runs; no client-supplied
    owner or scope label participates in the query.
    """
    if not principal_scope_id:
        raise FinanceContextNotFound
    if request.operation == "verify":
        items = _verify_selected_entities(session, request)
    else:
        items = _read_selected_entities(session, request)
    if len(items) > request.max_results:
        raise FinanceContextSelectionError("finance_context_result_limit_exceeded")
    result = FinanceContextReadResponse(items=tuple(items))
    if len(result.model_dump_json().encode("utf-8")) > request.max_bytes:
        raise FinanceContextSelectionError("finance_context_response_too_large")
    return result


def _read_selected_entities(
    session: Session, request: FinanceContextReadRequest
) -> list[FinanceContextRecord]:
    refs_by_type: dict[str, list[FinanceContextEntityReference]] = {}
    for reference in request.entity_refs:
        refs_by_type.setdefault(reference.entity_type, []).append(reference)

    broad = bool(refs_by_type.get("portfolio"))
    if broad and (set(refs_by_type) - {"portfolio"}):
        raise FinanceContextSelectionError(
            "finance_context_broad_scope_must_be_explicit"
        )

    accounts = _selected_accounts(
        session, refs_by_type.get("account", ()), broad, request
    )
    securities = _selected_securities(
        session, refs_by_type.get("security", ()), accounts, broad, request
    )
    items: list[FinanceContextRecord] = []

    if set(request.fields) == {"amount", "currency", "period"}:
        if (
            request.purpose != "shopping_discretionary_budget"
            or request.destination_application_id != "shopping"
        ):
            raise FinanceContextSelectionError(
                "finance_context_budget_export_scope_invalid"
            )
        for reference in refs_by_type.get("discretionary_budget", ()):
            budget = session.get(MonthlyDiscretionaryBudget, UUID(reference.entity_id))
            if budget is None or not budget.share_with_shopping:
                raise FinanceContextNotFound
            version = _monthly_budget_source_version(budget)
            source_id = f"finance:monthly_discretionary_budget:{budget.id}"
            values = {
                "amount": _value(
                    format(budget.amount, ".2f"),
                    source_identity="finance.monthly_discretionary_budget",
                    source_version=version,
                    quality="owner_entered",
                    authority="user_asserted",
                    as_of=budget.period,
                    unit="currency_amount",
                    currency=budget.currency,
                    evidence_refs=(str(budget.id),),
                ),
                "currency": _value(
                    budget.currency,
                    source_identity="finance.monthly_discretionary_budget",
                    source_version=version,
                    quality="owner_entered",
                    authority="user_asserted",
                    as_of=budget.period,
                    evidence_refs=(str(budget.id),),
                ),
                "period": _value(
                    budget.period,
                    source_identity="finance.monthly_discretionary_budget",
                    source_version=version,
                    quality="owner_entered",
                    authority="user_asserted",
                    as_of=budget.period,
                    evidence_refs=(str(budget.id),),
                ),
            }
            items.append(
                _record(
                    "discretionary_budget",
                    str(budget.id),
                    source_id=source_id,
                    source_version=version,
                    source_class="domain_current",
                    authority="user_asserted",
                    payload={"discretionary_budget": values},
                    refs=(str(budget.id),),
                    observed_at=_iso(budget.updated_at),
                    effective_at=f"{budget.period}-01",
                    permission_version=version,
                    permission_purpose="shopping_discretionary_budget",
                )
            )

    if "account_summary" in request.fields or "balance_summary" in request.fields:
        if not accounts:
            raise FinanceContextSelectionError(
                "finance_context_account_selection_required"
            )
        for account in accounts:
            items.append(_account_record(session, account, request.fields))

    if "security_summary" in request.fields:
        if not securities:
            raise FinanceContextSelectionError(
                "finance_context_security_selection_required"
            )
        items.extend(_security_records(securities))

    if "position_summary" in request.fields:
        if not accounts or not securities:
            raise FinanceContextSelectionError(
                "finance_context_position_scope_required"
            )
        items.extend(
            _position_records(
                session,
                accounts,
                securities,
                max_results=request.max_results - len(items),
            )
        )

    if "research_thesis" in request.fields:
        issuer_refs = refs_by_type.get("issuer", ())
        if not issuer_refs:
            raise FinanceContextSelectionError(
                "finance_context_issuer_selection_required"
            )
        items.extend(_thesis_records(session, issuer_refs))

    if "research_fact" in request.fields:
        fact_refs = refs_by_type.get("research_fact", ())
        if not fact_refs:
            raise FinanceContextSelectionError(
                "finance_context_fact_selection_required"
            )
        items.extend(_research_fact_records(session, fact_refs))

    return items


def _selected_accounts(
    session: Session,
    refs: tuple[FinanceContextEntityReference, ...]
    | list[FinanceContextEntityReference],
    broad: bool,
    request: FinanceContextReadRequest,
) -> list[Account]:
    if refs:
        account_ids = [UUID(ref.entity_id) for ref in refs]
        rows = list(
            session.scalars(
                select(Account)
                .where(Account.id.in_(account_ids), Account.active.is_(True))
                .order_by(Account.id)
            )
        )
        if len(rows) != len(account_ids):
            raise FinanceContextNotFound
        return rows
    if not broad:
        return []
    rows = list(
        session.scalars(
            select(Account)
            .where(Account.active.is_(True))
            .order_by(Account.id)
            .limit(request.max_results + 1)
        )
    )
    if len(rows) > request.max_results:
        raise FinanceContextSelectionError("finance_context_result_limit_exceeded")
    return rows


def _selected_securities(
    session: Session,
    refs: tuple[FinanceContextEntityReference, ...]
    | list[FinanceContextEntityReference],
    accounts: list[Account],
    broad: bool,
    request: FinanceContextReadRequest,
) -> list[Security]:
    if refs:
        security_ids = [UUID(ref.entity_id) for ref in refs]
        rows = list(
            session.scalars(
                select(Security)
                .where(Security.id.in_(security_ids))
                .order_by(Security.id)
            )
        )
        if len(rows) != len(security_ids):
            raise FinanceContextNotFound
        return rows
    if not broad or "position_summary" not in request.fields:
        return []
    current_snapshot_ids = [
        account.current_position_snapshot_id
        for account in accounts
        if account.current_position_snapshot_id is not None
    ]
    if not current_snapshot_ids:
        return []
    rows = list(
        session.scalars(
            select(Security)
            .join(PositionSnapshotLine, PositionSnapshotLine.security_id == Security.id)
            .join(
                PositionSnapshot,
                PositionSnapshot.id == PositionSnapshotLine.snapshot_id,
            )
            .where(
                PositionSnapshot.id.in_(current_snapshot_ids),
                PositionSnapshot.status == "accepted",
            )
            .distinct()
            .order_by(Security.id)
            .limit(request.max_results + 1)
        )
    )
    if len(rows) > request.max_results:
        raise FinanceContextSelectionError("finance_context_result_limit_exceeded")
    return rows


def _account_record(
    session: Session, account: Account, requested_fields: tuple[str, ...]
) -> FinanceContextRecord:
    payload: dict[str, dict[str, FinanceSemanticValue]] = {}
    snapshot = (
        session.get(PositionSnapshot, account.current_position_snapshot_id)
        if account.current_position_snapshot_id is not None
        else None
    )
    if snapshot is not None and snapshot.status == "accepted":
        snapshot_as_of = _iso(snapshot.snapshot_at)
    else:
        snapshot_as_of = None

    if "account_summary" in requested_fields:
        payload["account_summary"] = {
            "account_type": _value(
                account.account_type,
                source_identity="finance.account",
                source_version=str(account.current_position_revision),
                quality="canonical",
                authority="authoritative",
                as_of=snapshot_as_of,
            ),
            "currency": _value(
                account.base_currency,
                source_identity="finance.account",
                source_version=str(account.current_position_revision),
                quality="canonical",
                authority="authoritative",
                as_of=snapshot_as_of,
                unit="currency",
                currency=account.base_currency,
            ),
            "position_revision": _value(
                str(account.current_position_revision),
                source_identity="finance.account",
                source_version=str(account.current_position_revision),
                quality="canonical",
                authority="authoritative",
                as_of=snapshot_as_of,
                unit="revision",
            ),
        }

    if "balance_summary" in requested_fields:
        balance = session.scalar(
            select(AccountBalanceObservation)
            .where(AccountBalanceObservation.account_id == account.id)
            .order_by(
                AccountBalanceObservation.as_of.desc(),
                AccountBalanceObservation.revision.desc(),
            )
            .limit(1)
        )
        if balance is None:
            payload["balance_summary"] = {
                "amount": _value(
                    None,
                    source_identity="finance.account_balance_observation",
                    source_version="none",
                    quality="unavailable",
                    authority="unknown",
                    state="unknown",
                    uncertainty="No balance observation is available.",
                    unit="currency_amount",
                    currency=account.base_currency,
                )
            }
        else:
            payload["balance_summary"] = {
                "amount": _value(
                    _decimal(balance.amount),
                    source_identity=f"finance.account_balance:{balance.source}",
                    source_version=f"{balance.as_of.isoformat()}:{balance.revision}",
                    quality=balance.quality_status,
                    authority="authoritative",
                    as_of=balance.as_of.isoformat(),
                    unit="currency_amount",
                    currency=balance.currency,
                    evidence_refs=(str(balance.id),),
                    state=_state(balance.quality_status),
                    uncertainty=_uncertainty(balance.quality_status),
                )
            }

    source_version = _account_source_version(session, account)
    return _record(
        "account",
        str(account.id),
        source_id=f"finance:account:{account.id}",
        source_version=source_version,
        source_class="domain_current",
        authority="authoritative",
        payload=payload,
        refs=(str(account.id),),
        observed_at=_iso(account.updated_at),
        effective_at=snapshot_as_of,
    )


def _security_records(securities: list[Security]) -> list[FinanceContextRecord]:
    records = []
    for security in securities:
        version = _security_source_version(security)
        record_source = f"finance:security:{security.id}"
        payload = {
            "security_summary": {
                "name": _value(
                    security.name,
                    source_identity="finance.security_catalog",
                    source_version=version,
                    quality="canonical",
                    authority="authoritative",
                    evidence_refs=(str(security.id),),
                ),
                "ticker": _value(
                    security.display_ticker,
                    source_identity="finance.security_catalog",
                    source_version=version,
                    quality="canonical" if security.display_ticker else "unknown",
                    authority="authoritative" if security.display_ticker else "unknown",
                    evidence_refs=(str(security.id),),
                    state="known" if security.display_ticker else "unknown",
                ),
                "security_type": _value(
                    security.security_type,
                    source_identity="finance.security_catalog",
                    source_version=version,
                    quality="canonical",
                    authority="authoritative",
                    evidence_refs=(str(security.id),),
                ),
                "currency": _value(
                    security.currency,
                    source_identity="finance.security_catalog",
                    source_version=version,
                    quality="canonical",
                    authority="authoritative",
                    unit="currency",
                    currency=security.currency,
                ),
            }
        }
        records.append(
            _record(
                "security",
                str(security.id),
                source_id=record_source,
                source_version=version,
                source_class="domain_current",
                authority="authoritative",
                payload=payload,
                refs=(str(security.id),),
                observed_at=_iso(security.updated_at),
            )
        )
    return records


def _position_records(
    session: Session,
    accounts: list[Account],
    securities: list[Security],
    *,
    max_results: int,
) -> list[FinanceContextRecord]:
    if max_results <= 0:
        raise FinanceContextSelectionError("finance_context_result_limit_exceeded")
    items: list[FinanceContextRecord] = []
    remaining = max_results
    for account in accounts:
        snapshot = (
            session.get(PositionSnapshot, account.current_position_snapshot_id)
            if account.current_position_snapshot_id is not None
            else None
        )
        if snapshot is None or snapshot.status != "accepted":
            continue
        lines = list(
            session.scalars(
                select(PositionSnapshotLine)
                .where(
                    PositionSnapshotLine.snapshot_id == snapshot.id,
                    PositionSnapshotLine.security_id.in_(
                        [security.id for security in securities]
                    ),
                )
                .order_by(PositionSnapshotLine.id)
                .limit(remaining + 1)
            )
        )
        if len(lines) > remaining:
            raise FinanceContextSelectionError("finance_context_result_limit_exceeded")
        for line in lines:
            security = next(item for item in securities if item.id == line.security_id)
            as_of = _iso(snapshot.snapshot_at)
            quality = line.quality_status
            version = _position_source_version(account, snapshot, line, security)
            values = {
                "quantity": _value(
                    _decimal(line.quantity),
                    source_identity=f"finance.position:{line.source}",
                    source_version=version,
                    quality=quality,
                    authority="authoritative",
                    as_of=as_of,
                    unit="shares",
                    evidence_refs=(str(snapshot.id), str(line.id)),
                    state=_state(quality),
                    uncertainty=_uncertainty(quality),
                    semantic_class=_semantic_class(quality),
                ),
                "reported_value": _value(
                    _decimal(line.reported_value)
                    if line.reported_value is not None
                    else None,
                    source_identity=f"finance.position:{line.source}",
                    source_version=version,
                    quality=quality if line.reported_value is not None else "unknown",
                    authority="authoritative"
                    if line.reported_value is not None
                    else "unknown",
                    as_of=as_of,
                    unit="currency_amount",
                    currency=line.currency,
                    evidence_refs=(str(snapshot.id), str(line.id)),
                    state=("known" if line.reported_value is not None else "unknown"),
                    uncertainty=(
                        None
                        if line.reported_value is not None
                        else "No source value was reported."
                    ),
                    semantic_class=_semantic_class(quality),
                ),
                "reported_price": _value(
                    _decimal(line.reported_price)
                    if line.reported_price is not None
                    else None,
                    source_identity=f"finance.position:{line.source}",
                    source_version=version,
                    quality=quality if line.reported_price is not None else "unknown",
                    authority="authoritative"
                    if line.reported_price is not None
                    else "unknown",
                    as_of=as_of,
                    unit="price_per_share",
                    currency=line.currency,
                    evidence_refs=(str(snapshot.id), str(line.id)),
                    state=("known" if line.reported_price is not None else "unknown"),
                    uncertainty=(
                        None
                        if line.reported_price is not None
                        else "No source price was reported."
                    ),
                    semantic_class=_semantic_class(quality),
                ),
                "security": _value(
                    security.display_ticker or security.name,
                    source_identity="finance.security_catalog",
                    source_version=_version(str(security.updated_at)),
                    quality="canonical",
                    authority="authoritative",
                    evidence_refs=(str(security.id),),
                ),
            }
            items.append(
                _record(
                    "position",
                    str(line.id),
                    source_id=f"finance:position_snapshot:{snapshot.id}",
                    source_version=version,
                    source_class="domain_current",
                    authority="authoritative",
                    payload={"position_summary": values},
                    refs=(
                        str(snapshot.id),
                        str(line.id),
                        str(account.id),
                        str(security.id),
                    ),
                    observed_at=_iso(snapshot.accepted_at or snapshot.snapshot_at),
                    effective_at=as_of,
                )
            )
            remaining -= 1
    return items


def _thesis_records(
    session: Session,
    refs: tuple[FinanceContextEntityReference, ...]
    | list[FinanceContextEntityReference],
) -> list[FinanceContextRecord]:
    records: list[FinanceContextRecord] = []
    for reference in refs:
        issuer_id = UUID(reference.entity_id)
        issuer = session.get(Issuer, issuer_id)
        if issuer is None:
            raise FinanceContextNotFound
        note = session.scalar(
            select(ResearchThesisNote)
            .where(ResearchThesisNote.issuer_id == issuer_id)
            .order_by(ResearchThesisNote.version.desc())
            .limit(1)
        )
        if note is None:
            continue
        version = _thesis_source_version(note, issuer)
        records.append(
            _record(
                "research_thesis",
                str(note.id),
                source_id=f"finance:research_thesis:{issuer.id}",
                source_version=version,
                source_class="domain_current",
                authority="user_asserted",
                payload={
                    "research_thesis": {
                        "text": _value(
                            note.text,
                            source_identity="finance.user_thesis_note",
                            source_version=version,
                            quality="user_authored",
                            authority="user_asserted",
                            as_of=_iso(note.created_at),
                            evidence_refs=(str(note.id),),
                            semantic_class="observed",
                        ),
                        "issuer": _value(
                            issuer.display_name,
                            source_identity="finance.issuer_catalog",
                            source_version=_version(issuer.display_name),
                            quality="canonical",
                            authority="authoritative",
                            evidence_refs=(str(issuer.id),),
                        ),
                    }
                },
                refs=(str(note.id), str(issuer.id)),
                observed_at=_iso(note.created_at),
            )
        )
    return records


def _research_fact_records(
    session: Session,
    refs: tuple[FinanceContextEntityReference, ...]
    | list[FinanceContextEntityReference],
) -> list[FinanceContextRecord]:
    records: list[FinanceContextRecord] = []
    for reference in refs:
        fact_id = UUID(reference.entity_id)
        result = session.execute(
            select(ReportedFact, ResearchDocument)
            .join(ResearchDocument, ResearchDocument.id == ReportedFact.document_id)
            .where(ReportedFact.id == fact_id)
        ).first()
        if result is None:
            raise FinanceContextNotFound
        fact, document = result
        version = _research_fact_source_version(fact, document)
        state = _state(fact.quality_status)
        effective_date = fact.instant if fact.instant is not None else fact.period_end
        effective_at = (
            effective_date.isoformat() if effective_date is not None else None
        )
        records.append(
            _record(
                "research_fact",
                str(fact.id),
                source_id=f"finance:reported_fact:{fact.id}",
                source_version=version,
                source_class="external_research",
                authority="user_asserted",
                payload={
                    "research_fact": {
                        "concept": _value(
                            f"{fact.taxonomy}:{fact.concept}",
                            source_identity="finance.reported_fact",
                            source_version=version,
                            quality=fact.quality_status,
                            authority="user_asserted",
                            as_of=effective_at,
                            evidence_refs=(str(fact.id), str(document.id)),
                            state=state,
                            uncertainty=_uncertainty(fact.quality_status),
                        ),
                        "value": _value(
                            _decimal(fact.normalized_value)
                            if fact.normalized_value is not None
                            else None,
                            source_identity=f"finance.research_document:{document.source_status}",
                            source_version=version,
                            quality=fact.quality_status,
                            authority="user_asserted",
                            as_of=effective_at,
                            unit=fact.unit,
                            currency=fact.currency,
                            evidence_refs=(str(fact.id), str(document.id)),
                            state=(
                                state
                                if fact.normalized_value is not None
                                else "unknown"
                            ),
                            uncertainty=(
                                _uncertainty(fact.quality_status)
                                or "No normalized value is available."
                                if fact.normalized_value is None
                                else _uncertainty(fact.quality_status)
                            ),
                            semantic_class=_semantic_class(fact.quality_status),
                        ),
                        "source_status": _value(
                            document.source_status,
                            source_identity="finance.research_document",
                            source_version=version,
                            quality=document.source_status,
                            authority="user_asserted",
                            evidence_refs=(str(document.id),),
                            state=("known" if document.source_status else "unknown"),
                        ),
                    }
                },
                refs=(str(fact.id), str(document.id)),
                observed_at=_iso(fact.created_at),
                effective_at=effective_at,
            )
        )
    return records


def _monthly_budget_source_version(budget: MonthlyDiscretionaryBudget) -> str:
    material = "|".join(
        (
            str(budget.id),
            budget.period,
            format(budget.amount, ".2f"),
            budget.currency,
            str(budget.revision),
            str(int(budget.share_with_shopping)),
            _iso(budget.updated_at) or "",
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _verify_selected_entities(
    session: Session,
    request: FinanceContextReadRequest,
) -> list[FinanceContextRecord]:
    records: list[FinanceContextRecord] = []
    for reference in request.entity_refs:
        entity_id = reference.entity_id
        source_class: FinanceContextSourceClass = "domain_current"
        authority: FinanceContextAuthority = "authoritative"
        entity_type: FinanceContextRecordEntityType
        if reference.entity_type == "portfolio":
            raise FinanceContextSelectionError(
                "finance_context_verify_portfolio_unsupported"
            )
        if reference.entity_type == "account":
            account = session.get(Account, UUID(entity_id))
            if account is None or not account.active:
                raise FinanceContextNotFound
            version = _account_source_version(session, account)
            entity_type = "account"
        elif reference.entity_type == "security":
            security = session.get(Security, UUID(entity_id))
            if security is None:
                raise FinanceContextNotFound
            version = _security_source_version(security)
            entity_type = "security"
        elif reference.entity_type == "position":
            line = session.get(PositionSnapshotLine, UUID(entity_id))
            if line is None or line.security_id is None:
                raise FinanceContextNotFound
            security = session.get(Security, line.security_id)
            if security is None:
                raise FinanceContextNotFound
            snapshot = session.get(PositionSnapshot, line.snapshot_id)
            account = session.get(Account, snapshot.account_id) if snapshot else None
            if (
                snapshot is None
                or snapshot.status != "accepted"
                or account is None
                or not account.active
                or account.current_position_snapshot_id != snapshot.id
            ):
                raise FinanceContextNotFound
            version = _position_source_version(account, snapshot, line, security)
            entity_type = "position"
        elif reference.entity_type == "research_thesis":
            note = session.get(ResearchThesisNote, UUID(entity_id))
            if note is None:
                raise FinanceContextNotFound
            latest_id = session.scalar(
                select(ResearchThesisNote.id)
                .where(ResearchThesisNote.issuer_id == note.issuer_id)
                .order_by(ResearchThesisNote.version.desc())
                .limit(1)
            )
            if latest_id != note.id:
                raise FinanceContextNotFound
            issuer = session.get(Issuer, note.issuer_id)
            if issuer is None:
                raise FinanceContextNotFound
            version = _thesis_source_version(note, issuer)
            entity_type = "research_thesis"
            authority = "user_asserted"
        elif reference.entity_type == "research_fact":
            fact = session.get(ReportedFact, UUID(entity_id))
            document = session.get(ResearchDocument, fact.document_id) if fact else None
            if fact is None or document is None:
                raise FinanceContextNotFound
            version = _research_fact_source_version(fact, document)
            entity_type = "research_fact"
            source_class = "external_research"
            authority = "user_asserted"
        elif reference.entity_type == "discretionary_budget":
            budget = session.get(MonthlyDiscretionaryBudget, UUID(entity_id))
            if budget is None or not budget.share_with_shopping:
                raise FinanceContextNotFound
            version = _monthly_budget_source_version(budget)
            entity_type = "discretionary_budget"
            authority = "user_asserted"
        elif reference.entity_type == "issuer":
            raise FinanceContextSelectionError(
                "finance_context_verify_entity_unsupported"
            )
        else:
            raise FinanceContextSelectionError(
                "finance_context_entity_type_unsupported"
            )
        records.append(
            _record(
                entity_type,
                entity_id,
                source_id=(
                    f"finance:monthly_discretionary_budget:{entity_id}"
                    if entity_type == "discretionary_budget"
                    else f"finance:{entity_type}:{entity_id}"
                ),
                source_version=version,
                source_class=source_class,
                authority=authority,
                payload={},
                refs=(entity_id,),
                permission_version=version,
                permission_purpose=(
                    request.purpose
                    if reference.entity_type == "discretionary_budget"
                    else "Recheck current Finance source and version."
                ),
            )
        )
    return records


def _record(
    entity_type: FinanceContextRecordEntityType,
    entity_id: str,
    *,
    source_id: str,
    source_version: str,
    source_class: FinanceContextSourceClass,
    authority: FinanceContextAuthority,
    payload: dict[str, dict[str, FinanceSemanticValue]],
    refs: tuple[str, ...],
    observed_at: str | None = None,
    effective_at: str | None = None,
    permission_version: str | None = None,
    permission_purpose: str = "Recheck current Finance source and version.",
) -> FinanceContextRecord:
    fingerprint = _version(source_id, source_version)
    dependency_version = permission_version or source_version
    permission = FinanceContextPermissionDependency(
        permission_id=f"finance_context_read:{entity_type}:{entity_id}",
        version=dependency_version,
        purpose=permission_purpose,
    )
    sensitivity_fields = (
        tuple(next(iter(payload.values())))
        if entity_type == "discretionary_budget" and payload
        else tuple(payload)
    )
    field_sensitivity = tuple(
        FinanceContextFieldSensitivity(field=field, sensitivity="restricted")
        for field in sensitivity_fields
    )
    return FinanceContextRecord(
        entity_type=entity_type,
        entity_id=entity_id,
        source_id=source_id,
        source_version=source_version,
        source_class=source_class,
        authority=authority,
        observed_at=observed_at,
        effective_at=effective_at,
        sensitivity="restricted",
        payload=payload,
        source_refs=tuple(
            FinanceContextSourceReference(
                kind="evidence" if entity_type == "research_fact" else "record",
                reference_id=reference,
                fingerprint=fingerprint,
            )
            for reference in refs[:8]
        ),
        permission_dependencies=(permission,),
        field_sensitivity=field_sensitivity,
    )


def _account_source_version(session: Session, account: Account) -> str:
    parts = [
        str(account.updated_at),
        str(account.current_position_revision),
        account.account_type,
        account.base_currency,
    ]
    snapshot = (
        session.get(PositionSnapshot, account.current_position_snapshot_id)
        if account.current_position_snapshot_id is not None
        else None
    )
    if snapshot is not None and snapshot.status == "accepted":
        parts.extend([str(snapshot.id), str(snapshot.revision)])
    balance = session.scalar(
        select(AccountBalanceObservation)
        .where(AccountBalanceObservation.account_id == account.id)
        .order_by(
            AccountBalanceObservation.as_of.desc(),
            AccountBalanceObservation.revision.desc(),
        )
        .limit(1)
    )
    if balance is not None:
        parts.extend(
            [
                str(balance.id),
                str(balance.revision),
                str(balance.as_of),
                str(balance.amount),
                balance.currency,
                balance.source,
                balance.quality_status,
            ]
        )
    return _version(*parts)


def _security_source_version(security: Security) -> str:
    return _version(
        str(security.updated_at),
        security.name,
        security.display_ticker or "",
        security.currency,
        security.security_type,
    )


def _thesis_source_version(note: ResearchThesisNote, issuer: Issuer) -> str:
    return _version(
        str(note.version),
        note.text,
        str(note.created_at),
        str(issuer.id),
        issuer.display_name,
    )


def _position_source_version(
    account: Account,
    snapshot: PositionSnapshot,
    line: PositionSnapshotLine,
    security: Security,
) -> str:
    """Fingerprint the exact accepted position projection and its dependencies."""
    return _version(
        str(account.current_position_revision),
        str(snapshot.id),
        str(snapshot.revision),
        str(snapshot.snapshot_at),
        str(snapshot.accepted_at),
        str(line.id),
        line.source,
        line.quality_status,
        str(line.quantity),
        str(line.reported_value),
        str(line.reported_price),
        line.currency,
        _security_source_version(security),
    )


def _research_fact_source_version(
    fact: ReportedFact, document: ResearchDocument
) -> str:
    return _version(
        str(fact.created_at),
        fact.quality_status,
        str(document.id),
        document.source_status,
        fact.taxonomy,
        fact.concept,
        str(fact.normalized_value),
        fact.unit or "",
        fact.currency or "",
        str(fact.instant or fact.period_end),
    )


def _value(
    value: JsonValue,
    *,
    source_identity: str,
    source_version: str,
    quality: str,
    authority: FinanceContextAuthority | Literal["unknown"],
    as_of: str | None = None,
    unit: str | None = None,
    currency: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    state: FinanceSemanticState | None = None,
    uncertainty: str | None = None,
    semantic_class: FinanceSemanticClass | None = None,
) -> FinanceSemanticValue:
    status = state or _state(quality)
    classification = semantic_class or _semantic_class(quality)
    if value is None and status == "known":
        status = "unknown"
    return FinanceSemanticValue(
        semantic_class=classification,
        value=value,
        state=status,
        unit=unit,
        currency=currency,
        as_of=as_of,
        source_identity=source_identity,
        source_version=source_version,
        evidence_refs=evidence_refs,
        quality=quality,
        uncertainty=uncertainty or _uncertainty(quality),
        authority=authority,
        sensitivity="restricted",
    )


def _semantic_class(quality: str) -> FinanceSemanticClass:
    value = quality.casefold()
    if "ai" in value or "model" in value:
        return "ai_interpreted"
    if "calculated" in value or "derived" in value:
        return "calculated"
    if "estimated" in value or "assumed" in value:
        return "assumed"
    return "observed"


def _state(quality: str) -> FinanceSemanticState:
    value = quality.casefold()
    if "conflict" in value or "discrepancy" in value:
        return "conflict"
    if "unknown" in value or "unavailable" in value:
        return "unknown"
    return "known"


def _uncertainty(quality: str) -> str | None:
    value = quality.casefold()
    if any(
        marker in value
        for marker in ("stale", "estimated", "unverified", "conflict", "unknown")
    ):
        return quality
    return None


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    return value.isoformat()


def _version(*values: str) -> str:
    body = json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(body).hexdigest()
