"""Same-codebase local polling runner using database optimistic lease fences."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Job, PrivateFile, utc_now
from app.domains import documents, jobs
from app.ingestion.brokerage_pdf import PdfExtractionError
from app.storage.file_store import PrivateFileStore


class _LeaseLost(RuntimeError):
    """The worker lost its lease before a bounded persistence transaction."""


def _stop_if_cancelled_or_stale(
    session_factory: sessionmaker[Session], claim: jobs.JobClaim
) -> bool:
    cancelled, stale = jobs.job_cancelled_or_stale(session_factory, claim)
    if cancelled:
        jobs.finish_cancelled_job(session_factory, claim)
        return True
    return stale


def _process_one(
    session_factory: sessionmaker[Session],
    file_root: str,
    *,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    claim = jobs.claim_next_job(
        session_factory, owner=worker_id, lease_seconds=lease_seconds
    )
    if claim is None:
        return False
    if claim.job_type != jobs.PDF_PREVIEW_JOB:
        jobs.fail_job(
            session_factory,
            claim,
            safe_error_code="unsupported_job_type",
            retryable=False,
        )
        return True
    if claim.account_id is None or claim.input_file_id is None:
        jobs.fail_job(
            session_factory,
            claim,
            safe_error_code="job_payload_incomplete",
            retryable=False,
        )
        return True
    if _stop_if_cancelled_or_stale(session_factory, claim):
        return True
    if not jobs.progress_job(
        session_factory,
        claim,
        stage="reading_private_source",
        current=0,
        total=1,
        lease_seconds=lease_seconds,
    ):
        _stop_if_cancelled_or_stale(session_factory, claim)
        return True

    with session_factory() as session:
        source = session.get(PrivateFile, claim.input_file_id)
        if source is None or source.content_type != "application/pdf":
            jobs.fail_job(
                session_factory,
                claim,
                safe_error_code="private_source_unavailable",
                retryable=False,
            )
            return True
        storage_key = source.storage_key
        content_hash = source.content_hash

    try:
        content = PrivateFileStore(file_root).read(storage_key)
        if hashlib.sha256(content).hexdigest() != content_hash:
            raise ValueError("private_source_integrity")
        if not jobs.progress_job(
            session_factory,
            claim,
            stage="extracting_and_staging_review",
            current=0,
            total=1,
            lease_seconds=lease_seconds,
        ):
            _stop_if_cancelled_or_stale(session_factory, claim)
            return True

        def fence(session: Session) -> None:
            now = utc_now()
            result = session.execute(
                update(Job)
                .where(
                    Job.id == claim.id,
                    Job.status == "running",
                    Job.lease_owner == claim.owner,
                    Job.lease_generation == claim.generation,
                    Job.cancel_requested.is_(False),
                )
                .values(
                    lease_until=now + timedelta(seconds=lease_seconds), updated_at=now
                )
                .execution_options(synchronize_session=False)
            )
            if getattr(result, "rowcount", None) != 1:
                raise _LeaseLost("Job lease is no longer current.")

        payload = claim.payload
        result = documents.create_brokerage_pdf_import(
            session_factory,
            PrivateFileStore(file_root),
            content=content,
            filename=str(payload["filename"]),
            account_id=claim.account_id,
            effective_date=date.fromisoformat(str(payload["effective_date"])),
            source_label=str(payload["source_label"]),
            idempotency_key=str(payload["import_idempotency_key"]),
            expected_account_revision=int(payload["expected_account_revision"]),
            max_rows=int(payload["max_rows"]),
            max_pages=int(payload["max_pages"]),
            parser_timeout_seconds=int(payload["parser_timeout_seconds"]),
            replace_existing=bool(payload["replace_existing"]),
            write_fence=fence,
        )
    except PdfExtractionError as exc:
        jobs.fail_job(
            session_factory,
            claim,
            safe_error_code=exc.code,
            retryable=False,
        )
        return True
    except (documents.DocumentError, ValueError):
        jobs.fail_job(
            session_factory,
            claim,
            safe_error_code="document_rejected",
            retryable=False,
        )
        return True
    except OSError:
        jobs.fail_job(
            session_factory,
            claim,
            safe_error_code="private_source_unavailable",
            retryable=False,
        )
        return True
    except Exception:
        jobs.fail_job(
            session_factory,
            claim,
            safe_error_code="worker_internal_error",
            retryable=True,
        )
        return True

    document_id, import_id, file_id, row_count, duplicate = result
    cancelled, stale = jobs.job_cancelled_or_stale(session_factory, claim)
    if cancelled:
        jobs.cancel_completed_work(session_factory, import_id)
        jobs.finish_cancelled_job(session_factory, claim)
        return True
    if stale:
        return True
    completed = jobs.complete_job(
        session_factory,
        claim,
        {
            "document_id": str(document_id),
            "position_import_id": str(import_id),
            "file_id": str(file_id),
            "row_count": row_count,
            "duplicate": duplicate,
        },
    )
    if not completed:
        cancelled, _stale = jobs.job_cancelled_or_stale(session_factory, claim)
        if cancelled:
            jobs.cancel_completed_work(session_factory, import_id)
            jobs.finish_cancelled_job(session_factory, claim)
    return True


async def run_worker(
    session_factory: sessionmaker[Session],
    file_root: str | Path,
    *,
    poll_interval_seconds: int,
    lease_seconds: int,
) -> None:
    """Poll the durable queue without holding DB transactions around parsing."""
    worker_id = str(uuid4())
    root = str(file_root)
    while True:
        operation = asyncio.create_task(
            asyncio.to_thread(
                _process_one,
                session_factory,
                root,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
        )
        try:
            processed = await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise
        except Exception:
            processed = False
        if not processed:
            await asyncio.sleep(poll_interval_seconds)
