"""Bounded OCC retry behavior always creates a fresh DB transaction."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Account
from app.db.transactions import is_retryable_transaction_error, run_database_unit


class SyntheticDriverError(Exception):
    def __init__(self, message: str, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def make_error(sqlstate: str) -> OperationalError:
    return OperationalError(
        "synthetic statement", {}, SyntheticDriverError("conflict", sqlstate)
    )


def test_occ_retry_uses_new_session_and_rolls_back_failed_attempt() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE attempts (value integer NOT NULL)"))
    sessions = sessionmaker(engine, expire_on_commit=False)
    seen_sessions: list[Session] = []
    call_count = 0
    provider_call_count = 1
    sleeps: list[float] = []

    def operation(session: Session) -> str:
        nonlocal call_count
        call_count += 1
        seen_sessions.append(session)
        session.execute(text("INSERT INTO attempts (value) VALUES (1)"))
        if call_count == 1:
            raise make_error("40001")
        return "committed"

    result = run_database_unit(
        sessions,
        operation,
        sleep=sleeps.append,
        jitter=lambda low, _high: low,
    )

    with engine.connect() as connection:
        count: int = connection.execute(
            text("SELECT count(*) FROM attempts")
        ).scalar_one()
    assert result == "committed"
    assert call_count == 2
    assert seen_sessions[0] is not seen_sessions[1]
    assert count == 1
    assert provider_call_count == 1
    assert len(sleeps) == 1
    engine.dispose()


def test_non_retryable_error_is_not_retried() -> None:
    attempts = 0

    def operation(_session: Session) -> None:
        nonlocal attempts
        attempts += 1
        raise make_error("23505")

    with pytest.raises(OperationalError):
        run_database_unit(
            sessionmaker(create_engine("sqlite://")),
            operation,
            sleep=lambda _delay: None,
        )
    assert attempts == 1


def test_postgres_deadlock_is_retryable() -> None:
    error = OperationalError(
        "synthetic statement", {}, SyntheticDriverError("deadlock", "40P01")
    )
    assert is_retryable_transaction_error(error)


def test_retry_exhaustion_stops_at_configured_cap() -> None:
    attempts = 0

    def operation(_session: Session) -> None:
        nonlocal attempts
        attempts += 1
        raise make_error("40001")

    with pytest.raises(OperationalError):
        run_database_unit(
            sessionmaker(create_engine("sqlite://")),
            operation,
            max_attempts=2,
            sleep=lambda _delay: None,
        )
    assert attempts == 2


def verify_actual_serialization_retry(engine: Engine) -> None:
    """Force a real lost-update conflict and prove fresh-transaction retry."""
    account_id = uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            Account(
                id=account_id,
                name="Serialization fixture",
                account_type="brokerage",
                base_currency="USD",
            )
        )
    serializable = engine.execution_options(isolation_level="SERIALIZABLE")
    sessions = sessionmaker(serializable)
    barrier = Barrier(2)

    def worker() -> tuple[int, int]:
        attempts = 0

        def operation(session: Session) -> int:
            nonlocal attempts
            attempts += 1
            value: int = session.execute(
                text("SELECT current_position_revision FROM accounts WHERE id=:id"),
                {"id": account_id},
            ).scalar_one()
            if attempts == 1:
                barrier.wait(timeout=10)
            session.execute(
                text(
                    "UPDATE accounts SET current_position_revision=:revision "
                    "WHERE id=:id"
                ),
                {"id": account_id, "revision": value + 1},
            )
            return int(value + 1)

        result = run_database_unit(sessions, operation, sleep=lambda _delay: None)
        return result, attempts

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        assert sorted(result for result, _ in results) == [1, 2]
        assert sorted(attempts for _, attempts in results) == [1, 2]
        with Session(engine) as session:
            assert (
                session.scalar(
                    text("SELECT current_position_revision FROM accounts WHERE id=:id"),
                    {"id": account_id},
                )
                == 2
            )
    finally:
        with Session(engine) as session, session.begin():
            session.execute(
                text("DELETE FROM accounts WHERE id=:id"), {"id": account_id}
            )


def test_postgres_real_serialization_conflict_retries_without_lost_update() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Disposable PostgreSQL required for a real serialization conflict")
    engine = create_engine(database_url, pool_size=2, max_overflow=0)
    try:
        verify_actual_serialization_retry(engine)
    finally:
        engine.dispose()
