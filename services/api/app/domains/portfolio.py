"""Manual position snapshot reads and revision checked replacements."""

from datetime import UTC, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
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


def read_positions(session: Session, account_id: UUID) -> PositionsEnvelope:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFound
    snapshot = session.scalar(
        select(PositionSnapshot)
        .where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.source == MANUAL_SOURCE,
            PositionSnapshot.status == "accepted",
        )
        .order_by(PositionSnapshot.revision.desc(), PositionSnapshot.accepted_at.desc())
        .limit(1)
    )
    if snapshot is None:
        return PositionsEnvelope(snapshot=None)
    rows = _snapshot_lines(session, snapshot.id)
    return PositionsEnvelope(snapshot=_as_read(snapshot, rows))


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

    expected_revision = data.expected_revision or 0
    if account.current_position_revision != expected_revision:
        raise StaleRevision

    current = session.scalar(
        select(PositionSnapshot)
        .where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.source == MANUAL_SOURCE,
            PositionSnapshot.status == "accepted",
        )
        .order_by(PositionSnapshot.revision.desc(), PositionSnapshot.accepted_at.desc())
        .limit(1)
    )
    loaded = _load_positions(session, data.positions)
    snapshot_at = datetime.combine(data.effective_date, time.min, tzinfo=UTC)
    now = utc_now()
    next_revision = expected_revision + 1
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

    target = session.scalar(
        select(PositionSnapshot).where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.source == MANUAL_SOURCE,
            PositionSnapshot.snapshot_at == snapshot_at,
        )
    )
    if current is not None and current.id != (target.id if target else None):
        session.execute(
            update(PositionSnapshot)
            .where(
                PositionSnapshot.id == current.id,
                PositionSnapshot.status == "accepted",
            )
            .values(status="superseded", updated_at=now)
            .execution_options(synchronize_session=False)
        )
        current.status = "superseded"
        current.updated_at = now

    if target is None:
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
    else:
        session.execute(
            update(PositionSnapshot)
            .where(
                PositionSnapshot.id == target.id,
            )
            .values(
                revision=next_revision,
                snapshot_at=snapshot_at,
                valuation_source="manual",
                status="accepted",
                accepted_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        target.revision = next_revision
        target.snapshot_at = snapshot_at
        target.valuation_source = "manual"
        target.status = "accepted"
        target.accepted_at = now
        target.updated_at = now
        snapshot = target
        session.execute(
            delete(PositionSnapshotLine).where(
                PositionSnapshotLine.snapshot_id == snapshot.id
            )
        )

    for position, security in loaded:
        value: Decimal | None
        if security.security_type == "cash":
            value = Decimal(position.quantity)
        elif position.reported_price is not None:
            value = Decimal(position.quantity) * Decimal(position.reported_price)
        else:
            value = None
        if value is not None:
            value = value.quantize(VALUATION_QUANTUM, rounding=ROUND_HALF_UP)
        if value is not None and abs(value) >= Decimal("1e18"):
            raise ValuationOutOfRange
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
