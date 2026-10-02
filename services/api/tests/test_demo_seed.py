"""Idempotency, Decimal values, and reset isolation for the offline demo."""

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.models import (
    Account,
    Base,
    PositionSnapshot,
    PositionSnapshotLine,
    Quote,
    Security,
)
from app.demo_seed import (
    ACCOUNTS,
    DEMO_AS_OF_DATE,
    DEMO_SOURCE,
    DemoResetBlocked,
    fixture_id,
    reset_demo_data,
    seed_demo_data,
)


@pytest.fixture
def demo_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_seed_is_repeatable_and_totals_are_decimal(demo_engine: Engine) -> None:
    with Session(demo_engine) as session:
        with session.begin():
            first = seed_demo_data(session)
        with session.begin():
            second = seed_demo_data(session)

        assert first.issuers == 3
        assert first.aliases == 3
        assert first.securities == 5
        assert first.quotes == 4
        assert first.accounts == 2
        assert first.snapshots == 2
        assert first.position_lines == 6
        assert second == type(first)(0, 0, 0, 0, 0, 0, 0)

        expected_totals = {
            "taxable": Decimal("660.00"),
            "roth": Decimal("520.00"),
        }
        for fixture in ACCOUNTS:
            account_id = fixture_id("account", fixture.key)
            account = session.get(Account, account_id)
            assert account is not None
            assert account.source_type == "demo"
            snapshot = session.scalar(
                select(PositionSnapshot).where(
                    PositionSnapshot.account_id == account_id
                )
            )
            assert snapshot is not None
            assert snapshot.snapshot_at.date() == DEMO_AS_OF_DATE
            assert snapshot.revision == account.current_position_revision == 1
            lines = list(
                session.scalars(
                    select(PositionSnapshotLine).where(
                        PositionSnapshotLine.snapshot_id == snapshot.id
                    )
                )
            )
            assert (
                sum((line.reported_value or Decimal(0) for line in lines), Decimal(0))
                == expected_totals[fixture.key]
            )
            assert all(line.source == DEMO_SOURCE for line in lines)
            assert all(line.quality_status == "synthetic" for line in lines)

        cash = session.scalar(
            select(PositionSnapshotLine).where(
                PositionSnapshotLine.security_id == fixture_id("security", "cash-usd")
            )
        )
        assert cash is not None
        assert cash.quantity == Decimal("100.0000000000")
        assert cash.reported_price is None
        assert cash.reported_value == Decimal("100.0000000000")

        assert session.scalar(select(func.count()).select_from(Quote)) == 4
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 2


def test_seed_does_not_overwrite_demo_rows_after_user_edits(
    demo_engine: Engine,
) -> None:
    with Session(demo_engine) as session:
        with session.begin():
            seed_demo_data(session)
        account = session.get(Account, fixture_id("account", "taxable"))
        assert account is not None
        account.name = "My renamed example"
        line = session.scalar(
            select(PositionSnapshotLine).where(
                PositionSnapshotLine.id == fixture_id("position-line", "taxable:0")
            )
        )
        assert line is not None
        line.quantity = Decimal("9")
        session.commit()

        with session.begin():
            result = seed_demo_data(session)
        assert result.position_lines == 0
        renamed = session.get(Account, fixture_id("account", "taxable"))
        assert renamed is not None
        assert renamed.name == "My renamed example"
        assert line.quantity == Decimal("9")


def test_reset_removes_demo_rows_and_preserves_unrelated_rows(
    demo_engine: Engine,
) -> None:
    with Session(demo_engine) as session:
        with session.begin():
            seed_demo_data(session)
            unrelated_account = Account(
                id=fixture_id("test-account", "unrelated"),
                name="My separate account",
                account_type="taxable",
                base_currency="USD",
                active=True,
                current_position_revision=0,
                source_type="manual",
            )
            unrelated_security = Security(
                id=fixture_id("test-security", "unrelated"),
                security_type="equity",
                display_ticker="OWN",
                name="Unrelated synthetic holding",
                currency="USD",
            )
            session.add_all([unrelated_account, unrelated_security])

        with session.begin():
            removed_lines = reset_demo_data(session)
        assert removed_lines == 6
        assert session.get(Account, fixture_id("test-account", "unrelated")) is not None
        assert (
            session.get(Security, fixture_id("test-security", "unrelated")) is not None
        )
        assert session.get(Account, fixture_id("account", "taxable")) is None
        assert session.get(Security, fixture_id("security", "equity-northstar")) is None
        assert session.scalar(select(func.count()).select_from(Quote)) == 0


def test_reset_refuses_demo_securities_referenced_by_a_manual_account(
    demo_engine: Engine,
) -> None:
    with Session(demo_engine) as session:
        with session.begin():
            seed_demo_data(session)
            account_id = fixture_id("test-account", "external-reference")
            session.add(
                Account(
                    id=account_id,
                    name="Separate manual account",
                    account_type="taxable",
                    base_currency="USD",
                    active=True,
                    current_position_revision=1,
                    source_type="manual",
                )
            )
            snapshot = PositionSnapshot(
                id=fixture_id("test-snapshot", "external-reference"),
                account_id=account_id,
                snapshot_at=datetime(2026, 9, 30, 16, 0, tzinfo=UTC),
                source="manual",
                status="accepted",
                revision=1,
            )
            session.add(snapshot)
            session.flush()
            session.add(
                PositionSnapshotLine(
                    id=fixture_id("test-line", "external-reference"),
                    snapshot_id=snapshot.id,
                    security_id=fixture_id("security", "equity-northstar"),
                    quantity=Decimal("1"),
                    reported_value=Decimal("120"),
                    reported_price=Decimal("120"),
                    currency="USD",
                    source="manual",
                    quality_status="manual",
                )
            )

        with session.begin(), pytest.raises(DemoResetBlocked):
            reset_demo_data(session)
        assert session.get(Account, fixture_id("account", "taxable")) is not None
