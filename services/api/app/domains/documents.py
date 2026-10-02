"""Private source files and deterministic brokerage-statement preparation."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Account, DocumentImport, ImportAttempt, PrivateFile, utc_now
from app.db.transactions import run_database_unit
from app.domains import imports
from app.ingestion.brokerage_pdf import PDF_PARSER_VERSION, parse_brokerage_pdf
from app.storage.file_store import PrivateFileStore


class DocumentError(ValueError):
    """A safe document workflow failure."""


class DocumentNotFound(DocumentError):
    """The document or private source does not exist."""


class DocumentConflict(DocumentError):
    """An idempotency key or source identity conflicts."""


def _filename(value: str) -> str:
    basename = Path(value.replace("\\", "/")).name
    clean = "".join(char for char in basename if char >= " " and char != "\x7f")
    clean = clean.strip()[:200]
    if not clean or len(clean) < 5 or not clean.casefold().endswith(".pdf"):
        raise DocumentError("Upload a PDF with a .pdf filename.")
    return clean


def _document_file(
    session: Session,
    *,
    digest: str,
    key: str,
    filename: str,
    size: int,
) -> PrivateFile:
    existing = session.scalar(
        select(PrivateFile).where(PrivateFile.content_hash == digest)
    )
    if existing is not None:
        if existing.content_type != "application/pdf":
            raise DocumentConflict("This source has a conflicting stored media type.")
        return existing
    row = PrivateFile(
        id=uuid4(),
        content_hash=digest,
        storage_key=key,
        original_name=filename,
        content_type="application/pdf",
        byte_size=size,
    )
    session.add(row)
    session.flush()
    return row


def create_brokerage_pdf_import(
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
    max_rows: int,
    max_pages: int,
    parser_timeout_seconds: int,
    replace_existing: bool,
    write_fence: Any | None = None,
) -> tuple[UUID, UUID, UUID, int, bool]:
    """Extract a supported text holdings table, then stage it through S1 review."""
    safe_name = _filename(filename)
    source_label = source_label.strip()
    if not 1 <= len(source_label) <= 100:
        raise DocumentError("Source label must contain 1 to 100 characters.")
    if not 1 <= len(idempotency_key) <= 128:
        raise DocumentError("A valid idempotency key is required.")
    if effective_date > date.today():
        raise DocumentError("Position observations cannot be dated in the future.")
    if not content or len(content) > 20_000_000 or not content.startswith(b"%PDF-"):
        raise DocumentError("Upload a non-empty PDF within the configured size limit.")

    with session_factory() as session:
        account = session.get(Account, account_id)
        if account is None or not account.active:
            raise DocumentNotFound("Active account not found.")
        currency = account.base_currency

    csv_content, diagnostics = parse_brokerage_pdf(
        content,
        currency=currency,
        timeout_seconds=parser_timeout_seconds,
        max_pages=max_pages,
        max_rows=max_rows,
        effective_date=effective_date,
    )

    file_key, digest = file_store.put(content)

    def persist(operation: Any) -> Any:
        def execute(session: Session) -> Any:
            if write_fence is not None:
                write_fence(session)
            return operation(session)

        return run_database_unit(session_factory, execute)

    original_file = persist(
        lambda session: _document_file(
            session,
            digest=digest,
            key=file_key,
            filename=safe_name,
            size=len(content),
        ),
    )

    def prior_attempt(session: Session) -> DocumentImport | None:
        by_key = session.scalar(
            select(DocumentImport).where(
                DocumentImport.idempotency_key == idempotency_key
            )
        )
        if by_key is not None:
            if (
                by_key.file_id != original_file.id
                or by_key.account_id != account_id
                or by_key.effective_date != effective_date
            ):
                raise DocumentConflict(
                    "Idempotency key was already used for another document."
                )
            return by_key
        return session.scalar(
            select(DocumentImport)
            .where(
                DocumentImport.file_id == original_file.id,
                DocumentImport.account_id == account_id,
                DocumentImport.effective_date == effective_date,
                DocumentImport.parser_version == PDF_PARSER_VERSION,
                DocumentImport.position_import_id.not_in(
                    select(ImportAttempt.id).where(ImportAttempt.status == "cancelled")
                ),
            )
            .order_by(DocumentImport.created_at)
        )

    prior = persist(prior_attempt)
    if prior is not None:
        return (
            prior.id,
            prior.position_import_id,
            original_file.id,
            prior.row_count,
            True,
        )

    try:
        position_import_id, duplicate = imports.create_position_import(
            session_factory,
            file_store,
            content=csv_content,
            filename=f"{safe_name}.normalized.csv",
            account_id=account_id,
            effective_date=effective_date,
            source_label=source_label,
            mapping={
                "identifier": "identifier",
                "name": "name",
                "quantity": "quantity",
                "price": "price",
                "currency": "currency",
                "asset_type": "asset_type",
            },
            idempotency_key=idempotency_key,
            expected_account_revision=expected_account_revision,
            max_rows=max_rows,
            replace_existing=replace_existing,
            write_fence=write_fence,
        )
    except imports.ImportErrorBase as exc:
        raise DocumentError(str(exc)) from exc

    def record_document(session: Session) -> DocumentImport:
        attempt = session.get(ImportAttempt, position_import_id)
        if attempt is None:
            raise DocumentNotFound("Prepared position import is unavailable.")
        existing = session.scalar(
            select(DocumentImport).where(
                DocumentImport.file_id == original_file.id,
                DocumentImport.position_import_id == position_import_id,
            )
        )
        if existing is not None:
            return existing
        row = DocumentImport(
            id=uuid4(),
            file_id=original_file.id,
            position_import_id=position_import_id,
            account_id=account_id,
            effective_date=effective_date,
            source_label=source_label,
            parser_version=PDF_PARSER_VERSION,
            idempotency_key=idempotency_key,
            row_count=diagnostics["row_count"],
            status="review",
            diagnostics=diagnostics,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(row)
        session.flush()
        return row

    try:
        document = persist(record_document)
    except IntegrityError as exc:
        with session_factory() as session:
            raced = session.scalar(
                select(DocumentImport).where(
                    DocumentImport.file_id == original_file.id,
                    DocumentImport.position_import_id == position_import_id,
                )
            )
            if raced is None:
                raise DocumentConflict("Document import identity conflicted.") from exc
            document = raced
    return (
        document.id,
        position_import_id,
        original_file.id,
        int(document.row_count),
        duplicate,
    )


def read_document_import(session: Session, document_id: UUID) -> dict[str, Any]:
    document = session.get(DocumentImport, document_id)
    if document is None:
        raise DocumentNotFound
    attempt = session.get(ImportAttempt, document.position_import_id)
    source = session.get(PrivateFile, document.file_id)
    return {
        "id": document.id,
        "file_id": document.file_id,
        "position_import_id": document.position_import_id,
        "account_id": document.account_id,
        "effective_date": document.effective_date,
        "source_label": document.source_label,
        "parser_version": document.parser_version,
        # The linked Stage 1 position import owns review/publication state.
        # DocumentImport is created as "review" and otherwise immutable, so
        # report the current linked state instead of leaving this status stale.
        "status": attempt.status if attempt else document.status,
        "row_count": document.row_count,
        "diagnostics": document.diagnostics,
        "position_import_status": attempt.status if attempt else "unavailable",
        "filename": source.original_name if source else "statement.pdf",
    }


def read_document_file(
    session: Session, file_id: UUID, file_store: PrivateFileStore
) -> tuple[bytes, str, str]:
    source = session.scalar(
        select(PrivateFile)
        .join(DocumentImport, DocumentImport.file_id == PrivateFile.id)
        .where(PrivateFile.id == file_id)
    )
    if source is None:
        raise DocumentNotFound
    content = file_store.read(source.storage_key)
    if hashlib.sha256(content).hexdigest() != source.content_hash:
        raise DocumentError("Private source integrity check failed.")
    return content, source.content_type, source.original_name
