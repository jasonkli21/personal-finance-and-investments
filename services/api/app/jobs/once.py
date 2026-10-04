"""Bounded Cloud Run Job entrypoint over the existing Finance worker."""

import time
from collections.abc import Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.db.models import Job
from app.jobs.runner import _process_one
from app.storage.factory import create_file_store
from app.storage.file_store import FileStore


def run_bounded(
    session_factory: sessionmaker[Session],
    file_store: FileStore,
    *,
    lease_seconds: int,
    max_jobs: int = 20,
    max_seconds: int = 240,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if not 1 <= max_jobs <= 100 or not 1 <= max_seconds <= 240:
        raise ValueError("Worker execution bounds are invalid")
    deadline = clock() + max_seconds
    processed = 0
    worker_id = str(uuid4())
    while processed < max_jobs and clock() < deadline:
        if _process_one(
            session_factory,
            file_store,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        ):
            processed += 1
            continue
        with session_factory() as session:
            outstanding = session.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.status.in_(["pending", "running"]))
            )
        if not outstanding:
            break
        # Retry_wait is a progress stage on a pending row. Wait within this
        # execution for backoff or abandoned leases; never change DB state here.
        sleep(min(1, max(0, deadline - clock())))
    return processed


def main() -> None:
    settings = load_settings()
    engine = DatabaseEngineFactory.create(settings)
    try:
        run_bounded(
            sessionmaker(engine, expire_on_commit=False),
            create_file_store(settings),
            lease_seconds=settings.job_lease_seconds,
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
