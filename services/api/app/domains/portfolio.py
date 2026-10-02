"""Manual position snapshot reads and revision checked replacements."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from uuid import UUID, uuid4

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.api.contracts import (
    PositionInput,
    PositionLineRead,
    PositionReplace,
    PositionsEnvelope,
    PositionSnapshotRead,
    SecurityRead,
)
from app.db.models import (
    Account,
    PositionSnapshot,
    PositionSnapshotLine,
    Quote,
    Security,
    utc_now,
)
from app.domains.accounts import AccountNotFound

MANUAL_SOURCE = "manual"
VALUATION_QUANTUM = Decimal("0.0000000001")


class ArchivedAccount(Exception):
    """Archived accounts cannot receive new manual position revisions."""


class StaleRevision(Exception):
    """The client attempted to replace a revision that is no longer current."""


class UnknownSecurity(Exception):
    """A requested security does not exist in the local catalog."""


class DuplicatePositionSecurity(Exception):
    """A snapshot contains the same security more than once."""


class CurrencyMismatch(Exception):
    """The position currency must match its selected security's currency."""


class CashPriceNotAllowed(Exception):
    """Cash is entered as an explicit balance, not quantity times price."""


class ValuationOutOfRange(Exception):
    """The calculated value does not fit the portable NUMERIC column."""


class FutureObservation(Exception):
    """Owned position observations cannot be dated in the future."""


def _as_read(
    snapshot: PositionSnapshot,
    rows: list[tuple[PositionSnapshotLine, Security]],
) -> PositionSnapshotRead:
    effective_date = snapshot.snapshot_at.date()
    positions = [
        PositionLineRead(
            id=line.id,
            security=SecurityRead(
                id=security.id,
                security_type=security.security_type,
                display_ticker=security.display_ticker,
                name=security.name,
                currency=security.currency,
            ),
            quantity=str(line.quantity),
            reported_price=(
                str(line.reported_price) if line.reported_price is not None else None
            ),
            reported_value=(
                str(line.reported_value) if line.reported_value is not None else None
            ),
            currency=line.currency,
            price_as_of=effective_date if line.reported_price is not None else None,
            source=line.source,
            quality_status=line.quality_status,
        )
        for line, security in rows
    ]
    return PositionSnapshotRead(
        id=snapshot.id,
        account_id=snapshot.account_id,
        effective_date=effective_date,
        revision=snapshot.revision,
        source=snapshot.source,
        positions=positions,
    )


def _snapshot_lines(
    session: Session, snapshot_id: UUID
) -> list[tuple[PositionSnapshotLine, Security]]:
    statement = (
        select(PositionSnapshotLine, Security)
        .join(Security, PositionSnapshotLine.security_id == Security.id)
        .where(PositionSnapshotLine.snapshot_id == snapshot_id)
        .order_by(PositionSnapshotLine.id)
    )
    return [(row[0], row[1]) for row in session.execute(statement)]


def read_positions(
    session: Session, account_id: UUID, as_of: date | None = None
) -> PositionsEnvelope:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound
    if as_of is None:
        snapshot = (
            session.get(PositionSnapshot, account.current_position_snapshot_id)
            if account.current_position_snapshot_id is not None
            else None
        )
    else:
        cutoff = datetime.combine(as_of, time.max, tzinfo=UTC)
        snapshot = session.scalar(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.snapshot_at <= cutoff,
                PositionSnapshot.status.in_(("accepted", "superseded")),
            )
            .order_by(
                PositionSnapshot.snapshot_at.desc(),
                PositionSnapshot.revision.desc(),
                PositionSnapshot.id.desc(),
            )
            .limit(1)
        )
    if snapshot is None:
        return PositionsEnvelope(
            snapshot=None, current_revision=account.current_position_revision
        )
    rows = _snapshot_lines(session, snapshot.id)
    return PositionsEnvelope(
        snapshot=_as_read(snapshot, rows),
        current_revision=account.current_position_revision,
    )


def read_owned_valuation(
    session: Session, account_id: UUID, as_of: date | None = None
) -> dict[str, object]:
    """Value actual owned rows in USD using line prices before cached quotes."""
    envelope = read_positions(session, account_id, as_of)
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound
    snapshot = (
        session.get(PositionSnapshot, envelope.snapshot.id)
        if envelope.snapshot is not None
        else None
    )
    if snapshot is None:
        return {
            "account_id": account_id,
            "snapshot_id": None,
            "effective_date": None,
            "as_of": as_of,
            "current_revision": account.current_position_revision,
            "completeness": "empty",
            "known_usd_subtotal": "0",
            "total_usd": None,
            "percentages_available": False,
            "lines": [],
        }

    pairs = _snapshot_lines(session, snapshot.id)
    raw_lines: list[dict[str, object]] = []
    incomplete = False
    has_signed_value = False
    known_subtotal = Decimal(0)
    with localcontext() as context:
        context.prec = 80
        for line, security in pairs:
            price = line.reported_price
            price_as_of: datetime | None = (
                snapshot.snapshot_at if price is not None else None
            )
            price_source: str | None = line.source if price is not None else None
            quality = line.quality_status
            value: Decimal | None = None
            status_value = "unpriced"
            if security.security_type == "cash":
                value = (
                    line.reported_value
                    if line.reported_value is not None
                    else line.quantity
                )
                price = None
                price_as_of = snapshot.snapshot_at
                price_source = line.source
                status_value = (
                    "valued" if line.currency == "USD" else "foreign_currency"
                )
            elif price is None:
                selected = session.scalar(
                    select(Quote)
                    .where(
                        Quote.security_id == security.id,
                        Quote.currency == security.currency,
                        Quote.as_of <= snapshot.snapshot_at,
                    )
                    .order_by(
                        Quote.as_of.desc(),
                        case((Quote.quality_status == "reviewed", 1), else_=0).desc(),
                        Quote.source.asc(),
                        Quote.id.asc(),
                    )
                    .limit(1)
                )
                if selected is not None:
                    price = selected.price
                    price_as_of = selected.as_of
                    price_source = selected.source
                    quality = selected.quality_status
                    snapshot_time = snapshot.snapshot_at
                    quote_time = selected.as_of
                    if snapshot_time.tzinfo is None:
                        snapshot_time = snapshot_time.replace(tzinfo=UTC)
                    if quote_time.tzinfo is None:
                        quote_time = quote_time.replace(tzinfo=UTC)
                    if snapshot_time - quote_time > timedelta(days=7):
                        quality = "stale"
            if security.security_type != "cash" and price is not None:
                value = (line.quantity * price).quantize(
                    VALUATION_QUANTUM, rounding=ROUND_HALF_UP
                )
                status_value = (
                    "valued" if line.currency == "USD" else "foreign_currency"
                )
            if status_value == "valued" and value is not None:
                known_subtotal += value
                has_signed_value = has_signed_value or value < 0
            else:
                incomplete = True
            if quality == "stale":
                incomplete = True
            raw_lines.append(
                {
                    "position_id": line.id,
                    "security_id": security.id,
                    "ticker": security.display_ticker,
                    "name": security.name,
                    "quantity": str(line.quantity),
                    "currency": line.currency,
                    "value": str(value) if value is not None else None,
                    "value_currency": line.currency if value is not None else None,
                    "price": str(price) if price is not None else None,
                    "price_as_of": price_as_of,
                    "price_source": price_source,
                    "quality_status": quality,
                    "status": status_value,
                    "allocation_percent": None,
                }
            )

        percentages_available = (
            not incomplete and not has_signed_value and known_subtotal > 0
        )
        if percentages_available:
            for raw_line in raw_lines:
                line_value = raw_line["value"]
                if raw_line["status"] == "valued" and line_value is not None:
                    percent = Decimal(str(line_value)) / known_subtotal * Decimal(100)
                    raw_line["allocation_percent"] = str(
                        percent.quantize(
                            Decimal("0.0000000001"), rounding=ROUND_HALF_UP
                        )
                    )

    return {
        "account_id": account_id,
        "snapshot_id": snapshot.id,
        "effective_date": snapshot.snapshot_at.date(),
        "as_of": as_of,
        "current_revision": account.current_position_revision,
        "completeness": "incomplete" if incomplete else "complete",
        "known_usd_subtotal": str(known_subtotal),
        "total_usd": str(known_subtotal) if not incomplete else None,
        "percentages_available": percentages_available,
        "lines": raw_lines,
    }


def _load_positions(
    session: Session, positions: list[PositionInput]
) -> list[tuple[PositionInput, Security]]:
    seen: set[UUID] = set()
    loaded: list[tuple[PositionInput, Security]] = []
    for position in positions:
        if position.security_id in seen:
            raise DuplicatePositionSecurity
        seen.add(position.security_id)
        security = session.get(Security, position.security_id)
        if security is None:
            raise UnknownSecurity
        if position.currency != security.currency:
            raise CurrencyMismatch
        if security.security_type == "cash" and position.reported_price is not None:
            raise CashPriceNotAllowed
        loaded.append((position, security))
    return loaded


def replace_positions(
    session: Session, account_id: UUID, data: PositionReplace
) -> PositionSnapshotRead:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound
    if not account.active:
        raise ArchivedAccount
    if data.effective_date > date.today():
        raise FutureObservation

    expected_revision = data.expected_revision or 0
    if account.current_position_revision != expected_revision:
        raise StaleRevision

    loaded = _load_positions(session, data.positions)
    snapshot_at = datetime.combine(data.effective_date, time.min, tzinfo=UTC)
    now = utc_now()
    next_revision = expected_revision + 1

    # NUMERIC(28,10) has 18 integral digits. Individual request fields are
    # valid within NUMERIC(28,10)/NUMERIC(24,10), but their product may exceed
    # the value column. Use a bounded explicit context and reject before the
    # scale-changing quantize so Decimal's process-default precision cannot
    # leak an InvalidOperation through the API.
    calculated: list[tuple[PositionInput, Security, Decimal | None]] = []
    value_limit = Decimal("1e18")
    try:
        with localcontext() as context:
            context.prec = 80
            for position, security in loaded:
                if security.security_type == "cash":
                    value = Decimal(position.quantity)
                elif position.reported_price is not None:
                    value = Decimal(position.quantity) * Decimal(
                        position.reported_price
                    )
                else:
                    value = None
                if value is not None and abs(value) >= value_limit:
                    raise ValuationOutOfRange
                if value is not None:
                    value = value.quantize(VALUATION_QUANTUM, rounding=ROUND_HALF_UP)
                    if abs(value) >= value_limit:
                        raise ValuationOutOfRange
                calculated.append((position, security, value))
    except InvalidOperation as exc:
        raise ValuationOutOfRange from exc

    account_update = session.execute(
        update(Account)
        .where(
            Account.id == account_id,
            Account.current_position_revision == expected_revision,
        )
        .values(current_position_revision=next_revision, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if getattr(account_update, "rowcount", None) != 1:
        raise StaleRevision
    account.current_position_revision = next_revision
    account.updated_at = now
    if account.current_position_snapshot_id is not None:
        session.execute(
            update(PositionSnapshot)
            .where(
                PositionSnapshot.id == account.current_position_snapshot_id,
                PositionSnapshot.status == "accepted",
            )
            .values(status="superseded", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        previous = session.get(PositionSnapshot, account.current_position_snapshot_id)
        if previous is not None:
            previous.status = "superseded"
            previous.updated_at = now

    snapshot = PositionSnapshot(
        id=uuid4(),
        account_id=account_id,
        snapshot_at=snapshot_at,
        source=MANUAL_SOURCE,
        valuation_source="manual",
        status="accepted",
        revision=next_revision,
        accepted_at=now,
    )
    session.add(snapshot)
    session.flush()
    session.execute(
        update(Account)
        .where(
            Account.id == account_id,
            Account.current_position_revision == next_revision,
        )
        .values(current_position_snapshot_id=snapshot.id, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    account.current_position_snapshot_id = snapshot.id

    for position, security, value in calculated:
        session.add(
            PositionSnapshotLine(
                id=uuid4(),
                snapshot_id=snapshot.id,
                security_id=security.id,
                unresolved_ref=None,
                quantity=Decimal(position.quantity),
                reported_value=value,
                reported_price=(
                    Decimal(position.reported_price)
                    if position.reported_price is not None
                    else None
                ),
                currency=position.currency,
                original_row_ref=None,
                source=MANUAL_SOURCE,
                quality_status=("unavailable" if value is None else "manual"),
            )
        )
    session.flush()
    return _as_read(snapshot, _snapshot_lines(session, snapshot.id))
