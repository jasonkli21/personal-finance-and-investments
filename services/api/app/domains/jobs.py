"""Durable job enqueueing, optimistic leases and safe progress records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Account, DocumentImport, Job, PrivateFile, utc_now
from app.db.transactions import run_database_unit
from app.domains import documents
from app.ingestion.brokerage_pdf import PDF_PARSER_VERSION
from app.storage.file_store import PrivateFileStore

PDF_PREVIEW_JOB = "brokerage_pdf_preview_v1"
JOB_LEASE_SECONDS = 30
JOB_MAX_ATTEMPTS = 3


class JobError(ValueError):
    """Safe failure in the durable local job workflow."""


class JobNotFound(JobError):
    """The requested job does not exist."""


class JobConflict(JobError):
    """The requested job transition is no longer current."""


@dataclass(frozen=True)
class JobClaim:
    id: UUID
    job_type: str
    account_id: UUID | None
    input_file_id: UUID | None
    payload: dict[str, Any]
    owner: str
    generation: int
    attempts: int
    max_attempts: int


def _read(row: Job) -> dict[str, Any]:
    return {
        "id": row.id,
        "job_type": row.job_type,
        "status": row.status,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "progress_stage": row.progress_stage,
        "progress_current": row.progress_current,
        "progress_total": row.progress_total,
        "cancel_requested": row.cancel_requested,
        "safe_error_code": row.safe_error_code,
        "result": row.result,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _pdf_payload(
    *,
    filename: str,
    account_id: UUID,
    effective_date: date,
    source_label: str,
    idempotency_key: str,
    expected_account_revision: int,
    replace_existing: bool,
    max_rows: int,
    max_pages: int,
    parser_timeout_seconds: int,
) -> dict[str, Any]:
    return {
        "filename": filename,
        "account_id": str(account_id),
        "effective_date": effective_date.isoformat(),
        "source_label": source_label,
        "import_idempotency_key": idempotency_key,
        "expected_account_revision": expected_account_revision,
        "replace_existing": replace_existing,
        "max_rows": max_rows,
        "max_pages": max_pages,
        "parser_timeout_seconds": parser_timeout_seconds,
        "parser_version": PDF_PARSER_VERSION,
    }


def enqueue_pdf_preview(
    session_factory: sessionmaker[Session],
    file_store: PrivateFileStore,
    *,
    content: bytes,
    filename: str,
    account_id: UUID,
    effective_date: date,
    source_label: str,
    idempotency_key: str,
    expected_account_revision: int,
    replace_existing: bool,
    max_file_bytes: int,
    max_rows: int,
    max_pages: int,
    parser_timeout_seconds: int,
    max_attempts: int,
) -> dict[str, Any]:
    """Store original bytes privately, then enqueue a bounded parser reference."""
    try:
        safe_name = documents._filename(filename)
    except documents.DocumentError as exc:
        raise JobError(str(exc)) from exc
    source_label = source_label.strip()
    if not 1 <= len(source_label) <= 100:
        raise JobError("Source label must contain 1 to 100 characters.")
    if not 1 <= len(idempotency_key) <= 128:
        raise JobError("A valid idempotency key is required.")
    if not content or len(content) > max_file_bytes or not content.startswith(b"%PDF-"):
        raise JobError("Upload a non-empty PDF within the configured size limit.")
    if effective_date > date.today():
        raise JobError("Position observations cannot be dated in the future.")
    file_key, digest = file_store.put(content)
    job_key = "pdf-preview:" + hashlib.sha256(idempotency_key.encode()).hexdigest()
    now = utc_now()
    payload = _pdf_payload(
        filename=safe_name,
        account_id=account_id,
        effective_date=effective_date,
        source_label=source_label,
        idempotency_key=idempotency_key,
        expected_account_revision=expected_account_revision,
        replace_existing=replace_existing,
        max_rows=max_rows,
        max_pages=max_pages,
        parser_timeout_seconds=parser_timeout_seconds,
    )

    def create(session: Session) -> Job:
        account = session.get(Account, account_id)
        if account is None or not account.active:
            raise JobNotFound("Active account not found.")
        source = documents._document_file(
            session,
            digest=digest,
            key=file_key,
            filename=safe_name,
            size=len(content),
        )
        existing_job = session.scalar(select(Job).where(Job.idempotency_key == job_key))
        if existing_job is not None:
            if (
                existing_job.input_file_id != source.id
                or existing_job.payload != payload
            ):
                raise JobConflict("Idempotency key was used for another document job.")
            return existing_job
        in_flight = session.scalars(
            select(Job)
            .where(
                Job.job_type == PDF_PREVIEW_JOB,
                Job.account_id == account_id,
                Job.input_file_id == source.id,
                Job.status.in_(("pending", "running", "completed")),
            )
            .order_by(Job.created_at.desc())
            .limit(20)
        )
        for prior_job in in_flight:
            if (
                prior_job.payload.get("effective_date") == effective_date.isoformat()
                and prior_job.payload.get("parser_version") == PDF_PARSER_VERSION
            ):
                return prior_job
        prior = session.scalar(
            select(DocumentImport)
            .where(
                DocumentImport.file_id == source.id,
                DocumentImport.account_id == account_id,
                DocumentImport.effective_date == effective_date,
                DocumentImport.parser_version == PDF_PARSER_VERSION,
            )
            .order_by(DocumentImport.created_at)
            .limit(1)
        )
        row = Job(
            id=uuid4(),
            job_type=PDF_PREVIEW_JOB,
            account_id=account_id,
            input_file_id=source.id,
            idempotency_key=job_key,
            payload=payload,
            result=(
                {
                    "document_id": str(prior.id),
                    "position_import_id": str(prior.position_import_id),
                    "file_id": str(prior.file_id),
                    "row_count": prior.row_count,
                    "duplicate": True,
                }
                if prior
                else None
            ),
            status="completed" if prior else "pending",
            attempts=0,
            max_attempts=max_attempts,
            run_after=now,
            lease_generation=0,
            cancel_requested=False,
            progress_stage="complete" if prior else "queued",
            progress_current=1 if prior else 0,
            progress_total=1,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row

    try:
        row = run_database_unit(session_factory, create)
    except IntegrityError as exc:
        with session_factory() as session:
            raced = session.scalar(select(Job).where(Job.idempotency_key == job_key))
            source = session.scalar(
                select(PrivateFile).where(PrivateFile.content_hash == digest)
            )
            if (
                raced is None
                or source is None
                or raced.input_file_id != source.id
                or raced.payload != payload
            ):
                raise JobConflict(
                    "Document job identity conflicted; retry the upload."
                ) from exc
            row = raced
    return _read(row)


def read_job(session: Session, job_id: UUID) -> dict[str, Any]:
    row = session.get(Job, job_id)
    if row is None:
        raise JobNotFound("Job not found.")
    return _read(row)


def cancel_job(session: Session, job_id: UUID) -> dict[str, Any]:
    row = session.get(Job, job_id)
    if row is None:
        raise JobNotFound("Job not found.")
    if row.status in {"completed", "failed", "cancelled"}:
        return _read(row)
    if row.status == "pending":
        row.status = "cancelled"
        row.progress_stage = "cancelled"
    elif row.lease_until is not None and row.lease_until <= utc_now():
        row.status = "cancelled"
        row.progress_stage = "cancelled"
        row.lease_generation += 1
        row.lease_owner = None
        row.lease_until = None
    else:
        row.cancel_requested = True
        row.progress_stage = "cancellation_requested"
    row.updated_at = utc_now()
    session.flush()
    return _read(row)


def claim_next_job(
    session_factory: sessionmaker[Session], *, owner: str, lease_seconds: int
) -> JobClaim | None:
    now = utc_now()

    def claim(session: Session) -> JobClaim | None:
        session.execute(
            update(Job)
            .where(
                Job.status == "running",
                Job.lease_until.is_not(None),
                Job.lease_until <= now,
                Job.attempts >= Job.max_attempts,
            )
            .values(
                status="failed",
                lease_owner=None,
                lease_until=None,
                safe_error_code="retry_exhausted",
                progress_stage="failed",
                updated_at=now,
            )
        )
        candidate = session.scalar(
            select(Job)
            .where(
                Job.cancel_requested.is_(False),
                Job.attempts < Job.max_attempts,
                or_(
                    and_(Job.status == "pending", Job.run_after <= now),
                    and_(
                        Job.status == "running",
                        Job.lease_until.is_not(None),
                        Job.lease_until <= now,
                    ),
                ),
            )
            .order_by(Job.run_after, Job.created_at, Job.id)
            .limit(1)
        )
        if candidate is None:
            return None
        generation = candidate.lease_generation + 1
        result = session.execute(
            update(Job)
            .where(
                Job.id == candidate.id,
                Job.lease_generation == candidate.lease_generation,
                Job.cancel_requested.is_(False),
                Job.attempts == candidate.attempts,
                or_(
                    and_(Job.status == "pending", Job.run_after <= now),
                    and_(
                        Job.status == "running",
                        Job.lease_until.is_not(None),
                        Job.lease_until <= now,
                    ),
                ),
            )
            .values(
                status="running",
                attempts=Job.attempts + 1,
                lease_owner=owner,
                lease_until=now + timedelta(seconds=lease_seconds),
                lease_generation=generation,
                progress_stage="processing",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(result, "rowcount", None) != 1:
            return None
        return JobClaim(
            id=candidate.id,
            job_type=candidate.job_type,
            account_id=candidate.account_id,
            input_file_id=candidate.input_file_id,
            payload=dict(candidate.payload),
            owner=owner,
            generation=generation,
            attempts=candidate.attempts + 1,
            max_attempts=candidate.max_attempts,
        )

    return run_database_unit(session_factory, claim)


def job_cancelled_or_stale(
    session_factory: sessionmaker[Session], claim: JobClaim
) -> tuple[bool, bool]:
    with session_factory() as session:
        row = session.get(Job, claim.id)
        if row is None:
            return True, False
        cancelled = row.status == "cancelled" or row.cancel_requested
        current = row.status == "running" and (
            row.lease_owner == claim.owner and row.lease_generation == claim.generation
        )
        return cancelled, not current


def progress_job(
    session_factory: sessionmaker[Session],
    claim: JobClaim,
    *,
    stage: str,
    current: int,
    total: int | None,
    lease_seconds: int,
) -> bool:
    now = utc_now()

    def update_progress(session: Session) -> bool:
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
                progress_stage=stage,
                progress_current=current,
                progress_total=total,
                lease_until=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return getattr(result, "rowcount", None) == 1

    return run_database_unit(session_factory, update_progress)


def complete_job(
    session_factory: sessionmaker[Session], claim: JobClaim, result: dict[str, Any]
) -> bool:
    now = utc_now()

    def complete(session: Session) -> bool:
        advanced = session.execute(
            update(Job)
            .where(
                Job.id == claim.id,
                Job.status == "running",
                Job.lease_owner == claim.owner,
                Job.lease_generation == claim.generation,
                Job.cancel_requested.is_(False),
            )
            .values(
                status="completed",
                result=result,
                progress_stage="complete",
                progress_current=1,
                progress_total=1,
                lease_owner=None,
                lease_until=None,
                safe_error_code=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return getattr(advanced, "rowcount", None) == 1

    return run_database_unit(session_factory, complete)


def cancel_completed_work(
    session_factory: sessionmaker[Session], import_id: UUID
) -> None:
    """Cancel unpublished staging when the user cancels during local parsing."""
    from app.db.models import ImportAttempt
    from app.domains import imports

    def cancel(session: Session) -> None:
        attempt = session.get(ImportAttempt, import_id)
        if attempt is None or attempt.status in {"published", "cancelled", "replaced"}:
            return
        imports.cancel_import(
            session,
            import_id,
            expected_revision=attempt.review_revision,
            reason="Cancelled while document processing was running",
        )

    run_database_unit(session_factory, cancel)


def finish_cancelled_job(
    session_factory: sessionmaker[Session], claim: JobClaim
) -> bool:
    now = utc_now()

    def finish(session: Session) -> bool:
        result = session.execute(
            update(Job)
            .where(
                Job.id == claim.id,
                Job.lease_owner == claim.owner,
                Job.lease_generation == claim.generation,
                or_(Job.cancel_requested.is_(True), Job.status == "cancelled"),
            )
            .values(
                status="cancelled",
                progress_stage="cancelled",
                lease_owner=None,
                lease_until=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return getattr(result, "rowcount", None) == 1

    return run_database_unit(session_factory, finish)


def fail_job(
    session_factory: sessionmaker[Session],
    claim: JobClaim,
    *,
    safe_error_code: str,
    retryable: bool,
) -> bool:
    now = utc_now()
    terminal = not retryable or claim.attempts >= claim.max_attempts
    delay = min(60, 2 ** max(0, claim.attempts - 1))

    def fail(session: Session) -> bool:
        result = session.execute(
            update(Job)
            .where(
                Job.id == claim.id,
                Job.status == "running",
                Job.lease_owner == claim.owner,
                Job.lease_generation == claim.generation,
            )
            .values(
                status=case(
                    (Job.cancel_requested.is_(True), "cancelled"),
                    else_="failed" if terminal else "pending",
                ),
                run_after=now + timedelta(seconds=delay),
                lease_owner=None,
                lease_until=None,
                safe_error_code=case(
                    (Job.cancel_requested.is_(True), None), else_=safe_error_code
                ),
                progress_stage=case(
                    (Job.cancel_requested.is_(True), "cancelled"),
                    else_="failed" if terminal else "retry_wait",
                ),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        return getattr(result, "rowcount", None) == 1

    return run_database_unit(session_factory, fail)
