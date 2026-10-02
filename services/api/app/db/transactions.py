"""Short bounded retry wrapper for database-only transaction units."""

import random
import time
from collections.abc import Callable

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker


def is_retryable_transaction_error(error: BaseException) -> bool:
    """Recognize PostgreSQL serialization failures and DSQL OCC conflicts."""
    original = getattr(error, "orig", error)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate == "40001":
        return True
    return "OC001" in str(original)


def run_database_unit[T](
    session_factory: sessionmaker[Session],
    operation: Callable[[Session], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.025,
    max_delay_seconds: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float, float], float] = random.uniform,
) -> T:
    """Retry a complete DB-only unit in a new session after OCC conflicts.

    Callers must finish provider, filesystem, and model work before entering
    this helper. The operation runs again on conflict, so it must contain only
    bounded and transactionally repeatable database work.
    """
    if not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 1 and 5")
    if base_delay_seconds < 0 or max_delay_seconds < base_delay_seconds:
        raise ValueError("retry delays must be non-negative and ordered")

    for attempt in range(max_attempts):
        try:
            with session_factory() as session:
                with session.begin():
                    result = operation(session)
                return result
        except DBAPIError as exc:
            if not is_retryable_transaction_error(exc) or attempt + 1 >= max_attempts:
                raise
            ceiling = min(max_delay_seconds, base_delay_seconds * (2**attempt))
            if ceiling:
                sleep(jitter(ceiling * 0.5, ceiling))

    raise RuntimeError("unreachable retry state")
