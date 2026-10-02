"""Explicit, synthetic-only Stage 0 demo seed and isolated reset commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.db.models import (
    Account,
    Issuer,
    IssuerAlias,
    PositionSnapshot,
    PositionSnapshotLine,
    Quote,
    Security,
)
from app.db.transactions import run_database_unit

DEMO_NAMESPACE = UUID("db719d9c-6d07-5b18-8be2-c2e5f75b61db")
DEMO_SOURCE = "synthetic_demo"
DEMO_AS_OF_DATE = date(2026, 9, 30)
DEMO_AS_OF = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)


def fixture_id(kind: str, key: str) -> UUID:
    """Return a stable application-generated identity for one fixture row."""
    return uuid5(DEMO_NAMESPACE, f"{kind}:{key}")


@dataclass(frozen=True)
class SecurityFixture:
    key: str
    security_type: str
    ticker: str | None
    name: str
    currency: str
    issuer_key: str | None
    price: Decimal | None


@dataclass(frozen=True)
class PositionFixture:
    security_key: str
    quantity: Decimal
    price: Decimal | None


@dataclass(frozen=True)
class AccountFixture:
    key: str
    name: str
    account_type: str
    positions: tuple[PositionFixture, ...]


SECURITIES = (
    SecurityFixture(
        "equity-northstar",
        "equity",
        "SYN1",
        "Northstar Example Systems",
        "USD",
        "issuer-northstar",
        Decimal("120.00"),
    ),
    SecurityFixture(
        "equity-cedar",
        "equity",
        "SYN2",
        "Cedar Example Works",
        "USD",
        "issuer-cedar",
        Decimal("40.00"),
    ),
    SecurityFixture(
        "etf-broad-market",
        "etf",
        "SYNX",
        "Example Broad Market Fund",
        "USD",
        "issuer-example-funds",
        Decimal("50.00"),
    ),
    SecurityFixture(
        "etf-bond-market",
        "etf",
        "SYNB",
        "Example Bond Fund",
        "USD",
        "issuer-example-funds",
        Decimal("80.00"),
    ),
    SecurityFixture(
        "cash-usd",
        "cash",
        None,
        "Synthetic US Dollar Cash",
        "USD",
        None,
        None,
    ),
)

ACCOUNTS = (
    AccountFixture(
        "taxable",
        "[SYNTHETIC] Taxable example",
        "taxable",
        (
            PositionFixture("equity-northstar", Decimal("3"), Decimal("120.00")),
            PositionFixture("etf-broad-market", Decimal("4"), Decimal("50.00")),
            PositionFixture("cash-usd", Decimal("100.00"), None),
        ),
    ),
    AccountFixture(
        "roth",
        "[SYNTHETIC] Roth IRA example",
        "roth_ira",
        (
            PositionFixture("equity-northstar", Decimal("2"), Decimal("120.00")),
            PositionFixture("equity-cedar", Decimal("5"), Decimal("40.00")),
            PositionFixture("etf-bond-market", Decimal("1"), Decimal("80.00")),
        ),
    ),
)


@dataclass(frozen=True)
class SeedResult:
    issuers: int
    aliases: int
    securities: int
    quotes: int
    accounts: int
    snapshots: int
    position_lines: int


def _add_missing(session: Session, model: type, row_id: UUID, **values: object) -> bool:
    if session.get(model, row_id) is not None:
        return False
    session.add(model(id=row_id, **values))
    session.flush()
    return True


def seed_demo_data(session: Session) -> SeedResult:
    """Add missing demo rows without changing any existing row or user edit."""
    counts = {
        "issuers": 0,
        "aliases": 0,
        "securities": 0,
        "quotes": 0,
        "accounts": 0,
        "snapshots": 0,
        "position_lines": 0,
    }
    issuer_names = {
        "issuer-northstar": "Northstar Example Systems",
        "issuer-cedar": "Cedar Example Works",
        "issuer-example-funds": "Example Fund Company",
    }
    for issuer_key, display_name in issuer_names.items():
        normalized = display_name.casefold()
        if _add_missing(
            session,
            Issuer,
            fixture_id("issuer", issuer_key),
            normalized_name=normalized,
            display_name=display_name,
        ):
            counts["issuers"] += 1

        alias = display_name
        alias_id = fixture_id("issuer-alias", issuer_key)
        if _add_missing(
            session,
            IssuerAlias,
            alias_id,
            issuer_id=fixture_id("issuer", issuer_key),
            alias=alias,
            normalized_alias=alias.casefold(),
            source=DEMO_SOURCE,
        ):
            counts["aliases"] += 1

    for fixture in SECURITIES:
        security_id = fixture_id("security", fixture.key)
        issuer_id = (
            fixture_id("issuer", fixture.issuer_key)
            if fixture.issuer_key is not None
            else None
        )
        if _add_missing(
            session,
            Security,
            security_id,
            security_type=fixture.security_type,
            display_ticker=fixture.ticker,
            name=fixture.name,
            issuer_id=issuer_id,
            currency=fixture.currency,
        ):
            counts["securities"] += 1

        if fixture.price is not None and _add_missing(
            session,
            Quote,
            fixture_id("quote", fixture.key),
            security_id=security_id,
            as_of=DEMO_AS_OF,
            price=fixture.price,
            currency=fixture.currency,
            source=DEMO_SOURCE,
            fetched_at=DEMO_AS_OF,
            quality_status="synthetic",
            provider_metadata={"fixture": "stage-0", "synthetic": True},
        ):
            counts["quotes"] += 1

    for account_fixture in ACCOUNTS:
        account_id = fixture_id("account", account_fixture.key)
        if _add_missing(
            session,
            Account,
            account_id,
            name=account_fixture.name,
            account_type=account_fixture.account_type,
            base_currency="USD",
            active=True,
            current_position_revision=0,
            source_type="demo",
        ):
            counts["accounts"] += 1

        existing_snapshot = session.scalar(
            select(PositionSnapshot.id).where(
                PositionSnapshot.account_id == account_id,
                PositionSnapshot.snapshot_at == DEMO_AS_OF,
                PositionSnapshot.source == "manual",
            )
        )
        if existing_snapshot is not None:
            continue

        # If a demo account already has a manually-entered snapshot at another
        # date, leave its revision history and current counter untouched.
        if (
            session.scalar(
                select(PositionSnapshot.id)
                .where(
                    PositionSnapshot.account_id == account_id,
                    PositionSnapshot.status == "accepted",
                )
                .limit(1)
            )
            is not None
        ):
            continue

        snapshot_id = fixture_id("snapshot", account_fixture.key)
        snapshot = PositionSnapshot(
            id=snapshot_id,
            account_id=account_id,
            snapshot_at=DEMO_AS_OF,
            source="manual",
            valuation_source=DEMO_SOURCE,
            status="accepted",
            revision=1,
            accepted_at=DEMO_AS_OF,
        )
        session.add(snapshot)
        session.flush()
        counts["snapshots"] += 1

        account = session.get(Account, account_id)
        assert account is not None
        account.current_position_revision = 1
        account.current_position_snapshot_id = snapshot_id
        for index, position in enumerate(account_fixture.positions):
            security_id = fixture_id("security", position.security_key)
            value = (
                position.quantity
                if position.price is None
                else position.quantity * position.price
            )
            session.add(
                PositionSnapshotLine(
                    id=fixture_id("position-line", f"{account_fixture.key}:{index}"),
                    snapshot_id=snapshot_id,
                    security_id=security_id,
                    unresolved_ref=None,
                    quantity=position.quantity,
                    reported_value=value,
                    reported_price=position.price,
                    currency="USD",
                    original_row_ref=f"stage-0:{account_fixture.key}:{index + 1}",
                    source=DEMO_SOURCE,
                    quality_status="synthetic",
                )
            )
            counts["position_lines"] += 1
        session.flush()

    return SeedResult(**counts)


class DemoResetBlocked(Exception):
    """The labelled demo rows have been used by non-demo data."""


def reset_demo_data(session: Session) -> int:
    """Delete labelled demo rows and refuse user-position edits or outside reuse."""
    account_ids = [fixture_id("account", fixture.key) for fixture in ACCOUNTS]
    security_ids = [fixture_id("security", fixture.key) for fixture in SECURITIES]
    issuer_ids = [
        fixture_id("issuer", key)
        for key in (
            "issuer-northstar",
            "issuer-cedar",
            "issuer-example-funds",
        )
    ]

    outside_lines = session.scalar(
        select(func.count())
        .select_from(PositionSnapshotLine)
        .join(
            PositionSnapshot,
            PositionSnapshotLine.snapshot_id == PositionSnapshot.id,
        )
        .where(
            PositionSnapshotLine.security_id.in_(security_ids),
            PositionSnapshot.account_id.not_in(account_ids),
        )
    )
    non_demo_quotes = session.scalar(
        select(func.count())
        .select_from(Quote)
        .where(Quote.security_id.in_(security_ids), Quote.source != DEMO_SOURCE)
    )
    outside_issuer_users = session.scalar(
        select(func.count())
        .select_from(Security)
        .where(Security.issuer_id.in_(issuer_ids), Security.id.not_in(security_ids))
    )
    unsafe_demo_snapshots = session.scalar(
        select(func.count())
        .select_from(PositionSnapshot)
        .outerjoin(
            PositionSnapshotLine,
            PositionSnapshotLine.snapshot_id == PositionSnapshot.id,
        )
        .where(
            PositionSnapshot.account_id.in_(account_ids),
            (
                (PositionSnapshot.source != "manual")
                | PositionSnapshotLine.id.is_(None)
                | (PositionSnapshotLine.source != DEMO_SOURCE)
            ),
        )
    )
    if (
        outside_lines
        or non_demo_quotes
        or outside_issuer_users
        or unsafe_demo_snapshots
    ):
        raise DemoResetBlocked(
            "Demo records are referenced or edited outside the synthetic seed. "
            "Preserve them and remove user-created references before resetting."
        )

    snapshot_ids = select(PositionSnapshot.id).where(
        PositionSnapshot.account_id.in_(account_ids)
    )
    removed = (
        session.scalar(
            select(func.count())
            .select_from(PositionSnapshotLine)
            .where(PositionSnapshotLine.snapshot_id.in_(snapshot_ids))
        )
        or 0
    )
    session.execute(
        update(Account)
        .where(Account.id.in_(account_ids))
        .values(current_position_snapshot_id=None)
    )
    session.execute(
        delete(PositionSnapshotLine).where(
            PositionSnapshotLine.snapshot_id.in_(snapshot_ids)
        )
    )
    session.execute(
        delete(PositionSnapshot).where(PositionSnapshot.account_id.in_(account_ids))
    )
    session.execute(
        delete(Quote).where(
            Quote.security_id.in_(security_ids), Quote.source == DEMO_SOURCE
        )
    )
    session.execute(delete(Security).where(Security.id.in_(security_ids)))
    session.execute(delete(IssuerAlias).where(IssuerAlias.issuer_id.in_(issuer_ids)))
    session.execute(delete(Issuer).where(Issuer.id.in_(issuer_ids)))
    session.execute(delete(Account).where(Account.id.in_(account_ids)))
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="destructively remove labelled synthetic demo records only",
    )
    args = parser.parse_args()
    settings = load_settings()
    if not settings.demo_mode:
        parser.error("Set DEMO_MODE=true to run demo seed/reset commands")
    engine = DatabaseEngineFactory.create(settings)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        if args.reset_demo:
            try:
                deleted_lines = run_database_unit(factory, reset_demo_data)
            except DemoResetBlocked as exc:
                parser.error(str(exc))
            print(f"Removed demo data and {deleted_lines} synthetic position lines.")
        else:
            result = run_database_unit(factory, seed_demo_data)
            print(f"Seeded missing synthetic demo rows: {result}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
