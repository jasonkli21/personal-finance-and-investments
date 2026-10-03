"""Consistent input capture and durable, checksum-verified derived reports."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import localcontext
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Account,
    Calculation,
    FundLine,
    FundSnapshot,
    Issuer,
    PositionSnapshot,
    PositionSnapshotLine,
    Security,
    utc_now,
)
from app.db.transactions import run_database_unit
from app.domains.exposure import VERSION, calculate
from app.providers.quotes import CachedQuoteProvider, QuoteProvider
from app.storage.file_store import FileStore


class ReportNotFound(Exception):
    """No immutable report or artifact available."""


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def capture(
    session: Session,
    account_ids: list[UUID],
    as_of: datetime | None,
    include_archived: bool,
    now: datetime,
    quote_provider: QuoteProvider | None = None,
) -> dict[str, Any]:
    provider = quote_provider or CachedQuoteProvider(session)
    time = aware(as_of or now)
    if time > now:
        raise ValueError("Future portfolio valuations are unsupported")
    accounts = list(session.scalars(select(Account).order_by(Account.id)))
    if account_ids and set(account_ids) - {a.id for a in accounts}:
        raise ValueError("An included account does not exist")
    included = [
        a
        for a in accounts
        if (not account_ids or a.id in account_ids) and (a.active or include_archived)
    ]
    catalog = {str(s.id): s for s in session.scalars(select(Security))}
    issuers = {str(i.id): i.display_name for i in session.scalars(select(Issuer))}

    def security(s: Security | None) -> dict[str, Any] | None:
        if not s:
            return None
        return {
            "id": str(s.id),
            "label": s.display_ticker or s.name,
            "type": s.security_type,
            "issuer_id": str(s.issuer_id) if s.issuer_id else None,
            "issuer_name": issuers.get(str(s.issuer_id)),
        }

    owned: list[dict[str, Any]] = []
    warnings = []
    policies: dict[str, Any] = {
        "quote_stale_days": int(os.environ.get("QUOTE_STALE_DAYS", "7")),
        "manual_fund_stale_days": int(os.environ.get("MANUAL_FUND_STALE_DAYS", "30")),
        "issuer_fund_stale_days": int(os.environ.get("ISSUER_FUND_STALE_DAYS", "7")),
        "valuation_mode": "historical" if as_of else "selected_head",
    }
    if any(
        policies[k] < 0
        for k in (
            "quote_stale_days",
            "manual_fund_stale_days",
            "issuer_fund_stale_days",
        )
    ):
        raise ValueError("Freshness days must be nonnegative")
    quote_priority = os.environ.get("QUOTE_SOURCE_PRIORITY", "manual,cached").split(",")
    fund_priority = os.environ.get("FUND_SOURCE_PRIORITY", "").split(",")
    policies["quote_source_priority"] = quote_priority
    policies["fund_source_priority"] = fund_priority

    def rank(source: str, priorities: list[str]) -> int:
        return priorities.index(source) if source in priorities else len(priorities)

    for account in included:
        snapshot = (
            session.scalar(
                select(PositionSnapshot)
                .where(
                    PositionSnapshot.account_id == account.id,
                    PositionSnapshot.status.in_(("accepted", "superseded")),
                    PositionSnapshot.snapshot_at <= time,
                )
                .order_by(
                    PositionSnapshot.snapshot_at.desc(),
                    PositionSnapshot.revision.desc(),
                )
                .limit(1)
            )
            if as_of
            else session.get(PositionSnapshot, account.current_position_snapshot_id)
            if account.current_position_snapshot_id
            else None
        )
        if (
            not snapshot
            or snapshot.status not in {"accepted", "superseded"}
            or aware(snapshot.snapshot_at) > time
        ):
            warnings.append(f"{account.name}: no eligible published snapshot")
            continue
        for line in session.scalars(
            select(PositionSnapshotLine)
            .where(PositionSnapshotLine.snapshot_id == snapshot.id)
            .order_by(PositionSnapshotLine.id)
        ):
            s = catalog.get(str(line.security_id))
            info = security(s)
            price = line.reported_price
            quote_id = None
            quote_date = aware(snapshot.snapshot_at) if price is not None else None
            quote_source = line.source if price is not None else None
            quality = line.quality_status
            if s and s.security_type != "cash":
                candidates = provider.observations(s.id, line.currency, time)
                q = (
                    min(
                        candidates,
                        key=lambda q: (
                            -aware(q.as_of).timestamp(),
                            -bool(q.provider_metadata.get("reviewed_override")),
                            rank(q.source, quote_priority),
                            str(q.id),
                        ),
                    )
                    if candidates
                    else None
                )
                if q and (
                    quote_date is None
                    or aware(q.as_of) > quote_date
                    or (
                        aware(q.as_of) == quote_date
                        and q.provider_metadata.get("reviewed_override")
                    )
                ):
                    price = q.price
                    quote_id = str(q.id)
                    quote_date = aware(q.as_of)
                    quote_source = q.source
                    quality = q.quality_status
            value = None
            state = "unpriced"
            if s and s.security_type == "cash":
                value = line.quantity
                state = "valued"
                quote_source = line.source
                quote_date = aware(snapshot.snapshot_at)
            elif price is not None:
                value = line.quantity * price
                state = "valued"
            if line.currency != "USD":
                state = "foreign_currency"
            if not s:
                state = "unresolved"
            stale = quote_date is not None and time - quote_date > timedelta(
                days=policies["quote_stale_days"]
            )
            if stale:
                quality = "stale"
            owned.append(
                {
                    "account_id": str(account.id),
                    "account_name": account.name,
                    "position_id": str(line.id),
                    "position_snapshot_id": str(snapshot.id),
                    "position_revision": snapshot.revision,
                    "position_as_of": aware(snapshot.snapshot_at).isoformat(),
                    "position_source": line.source,
                    "position_quality": line.quality_status,
                    "security_id": str(s.id) if s else None,
                    "security_type": s.security_type if s else "other",
                    "security": info,
                    "label": s.display_ticker or s.name
                    if s
                    else line.unresolved_ref or "Unresolved",
                    "quantity": str(line.quantity),
                    "price": str(price) if price is not None else None,
                    "value": str(value) if value is not None else None,
                    "currency": line.currency,
                    "status": state,
                    "quote_id": quote_id,
                    "quote_as_of": quote_date.isoformat() if quote_date else None,
                    "quote_source": quote_source,
                    "quality_status": quality,
                    "stale": stale,
                }
            )
            if len(owned) > 10000:
                raise ValueError(
                    "Report exceeds 10,000 positions; select fewer accounts"
                )
    funds = {}
    for fund_id in sorted(
        {p["security_id"] for p in owned if p["security_type"] == "etf"}
    ):
        candidates_fund = list(
            session.scalars(
                select(FundSnapshot)
                .where(
                    FundSnapshot.fund_security_id == UUID(fund_id),
                    FundSnapshot.status == "published",
                    FundSnapshot.as_of <= time.date(),
                )
                .order_by(FundSnapshot.as_of.desc())
                .limit(10001)
            )
        )
        if len(candidates_fund) > 10000:
            raise ValueError("Fund history exceeds safe capture limit")
        fund_snapshot = (
            min(
                candidates_fund,
                key=lambda f: (
                    -f.as_of.toordinal(),
                    rank(f.source, fund_priority),
                    -aware(f.published_at).timestamp() if f.published_at else 0,
                    str(f.id),
                ),
            )
            if candidates_fund
            else None
        )
        if not fund_snapshot:
            continue
        threshold = (
            policies["manual_fund_stale_days"]
            if fund_snapshot.parser_version.startswith("manual")
            else policies["issuer_fund_stale_days"]
        )
        funds[fund_id] = {
            "id": str(fund_snapshot.id),
            "as_of": fund_snapshot.as_of.isoformat(),
            "fetched_at": aware(fund_snapshot.fetched_at).isoformat(),
            "source": fund_snapshot.source,
            "source_url": fund_snapshot.source_url,
            "quality_status": fund_snapshot.quality_status,
            "stale": time.date() - fund_snapshot.as_of > timedelta(days=threshold),
            "lines": [
                {
                    "id": str(fund_line.id),
                    "row_number": fund_line.row_number,
                    "weight": str(fund_line.weight),
                    "security": security(catalog.get(str(fund_line.security_id))),
                    "asset_type": fund_line.asset_type,
                    "raw_name": fund_line.raw_name,
                    "raw_identifier": fund_line.raw_identifier,
                }
                for fund_line in session.scalars(
                    select(FundLine)
                    .where(FundLine.snapshot_id == fund_snapshot.id)
                    .order_by(FundLine.row_number)
                )
            ],
        }
    return {
        "owned": owned,
        "funds": funds,
        "warnings": warnings,
        "account_ids": [str(a.id) for a in included],
        "valuation_at": time.isoformat(),
        "policies": policies,
        "include_archived": include_archived,
    }


def create(
    factory: sessionmaker[Session],
    store: FileStore,
    *,
    account_ids: list[UUID],
    as_of: datetime | None,
    include_archived: bool = False,
) -> dict[str, Any]:
    now = utc_now()
    with factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        with localcontext() as context:
            context.prec = 80
            inputs = capture(session, account_ids, as_of, include_archived, now)
    result = calculate(inputs)
    identifier = uuid4()

    def canonical(value: object) -> bytes:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()

    input_hash = hashlib.sha256(canonical(inputs)).hexdigest()
    result.update(
        {
            "id": str(identifier),
            "generated_at": now.isoformat(),
            "valuation_at": inputs["valuation_at"],
            "account_ids": inputs["account_ids"],
            "input_hash": input_hash,
            "inputs": inputs,
        }
    )
    content = canonical(result)
    if len(content) > 20000000:
        raise ValueError("Report exceeds safe artifact size; select fewer accounts")
    (key, digest) = store.put(content)

    def persist(session: Session) -> None:
        session.add(
            Calculation(
                id=identifier,
                storage_key=key,
                content_hash=digest,
                input_hash=input_hash,
                calculation_version=VERSION,
                generated_at=now,
            )
        )

    run_database_unit(factory, persist)
    return result


def read(session: Session, store: FileStore, identifier: UUID) -> dict[str, Any]:
    record = session.get(Calculation, identifier)
    if record is None:
        raise ReportNotFound
    try:
        content = store.read(record.storage_key)
        if hashlib.sha256(content).hexdigest() != record.content_hash:
            raise ReportNotFound
        result: dict[str, Any] = json.loads(content)
        if result["id"] != str(identifier) or result["input_hash"] != record.input_hash:
            raise ReportNotFound
        return result
    except (OSError, ValueError, KeyError) as exc:
        raise ReportNotFound from exc
