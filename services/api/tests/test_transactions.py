"""Bounded OCC retry behavior always creates a fresh DB transaction."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

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


def test_aurora_dsql_occ_code_is_retryable() -> None:
    error = OperationalError(
        "synthetic statement", {}, SyntheticDriverError("OC001 conflict", "XX000")
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
