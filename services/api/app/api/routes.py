"""Versioned HTTP routes for the manual portfolio workflow."""

import asyncio
import json
from collections.abc import Iterator
from datetime import date
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import (
    AccountCreate,
    AccountPatch,
    AccountRead,
    DocumentImportRead,
    ErrorResponse,
    ImportAction,
    ImportCreated,
    ImportReviewRead,
    ImportRowCorrection,
    ImportRowRead,
    IssuerAssignment,
    IssuerCreate,
    IssuerRead,
    JobRead,
    OwnedPortfolioRead,
    PositionReplace,
    PositionsEnvelope,
    PositionSnapshotRead,
    QuoteCreate,
    QuoteRead,
    SecurityCreate,
    SecurityRead,
    SecurityResolution,
)
from app.db.models import ImportAttempt, ImportBatch, Issuer, PositionSnapshot, Security
from app.db.transactions import run_database_unit
from app.domains import accounts, documents, imports, jobs, portfolio, securities
from app.storage.file_store import PrivateFileStore

router = APIRouter(
    prefix="/v1",
    responses={
        404: {"model": ErrorResponse, "description": "Requested resource not found"},
        409: {"model": ErrorResponse, "description": "Revision or state conflict"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def _security_read(security: Security) -> SecurityRead:
    return SecurityRead(
        id=security.id,
        security_type=security.security_type,
        display_ticker=security.display_ticker,
        name=security.name,
        currency=security.currency,
    )


@router.get("/accounts", response_model=list[AccountRead])
def get_accounts(session: SessionDependency) -> list[AccountRead]:
    return [AccountRead.model_validate(row) for row in accounts.list_accounts(session)]


@router.post(
    "/accounts", response_model=AccountRead, status_code=status.HTTP_201_CREATED
)
def post_account(request: Request, data: AccountCreate) -> AccountRead:
    result = run_database_unit(
        request.app.state.session_factory,
        lambda session: accounts.create_account(session, data),
    )
    return AccountRead.model_validate(result)


@router.patch("/accounts/{account_id}", response_model=AccountRead)
def patch_account(
    request: Request, account_id: UUID, data: AccountPatch
) -> AccountRead:
    if any(value is None for value in data.model_dump(exclude_unset=True).values()):
        raise HTTPException(status_code=422, detail="Account fields cannot be null")
    try:
        result = run_database_unit(
            request.app.state.session_factory,
            lambda session: accounts.edit_account(session, account_id, data),
        )
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    return AccountRead.model_validate(result)


@router.get("/securities/resolve", response_model=SecurityResolution)
def get_security_resolution(
    q: Annotated[str, Query(min_length=2, max_length=80)],
    session: SessionDependency,
) -> SecurityResolution:
    rows = securities.resolve_securities(session, q)
    limited = rows[:10]
    return SecurityResolution(
        status=(
            "unknown" if not rows else "resolved" if len(rows) == 1 else "ambiguous"
        ),
        matches=[_security_read(row) for row in limited],
    )


@router.get("/accounts/{account_id}/positions", response_model=PositionsEnvelope)
def get_positions(
    account_id: UUID,
    session: SessionDependency,
    as_of: Annotated[date | None, Query()] = None,
) -> PositionsEnvelope:
    try:
        return portfolio.read_positions(session, account_id, as_of)
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc


@router.get("/portfolio/owned/{account_id}", response_model=OwnedPortfolioRead)
def get_owned_portfolio(
    account_id: UUID,
    session: SessionDependency,
    as_of: Annotated[date | None, Query()] = None,
) -> OwnedPortfolioRead:
    try:
        return OwnedPortfolioRead.model_validate(
            portfolio.read_owned_valuation(session, account_id, as_of)
        )
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc


@router.post("/issuers", response_model=IssuerRead, status_code=status.HTTP_201_CREATED)
def post_issuer(request: Request, data: IssuerCreate) -> IssuerRead:
    try:
        issuer = run_database_unit(
            request.app.state.session_factory,
            lambda session: imports.issuer_create(session, data.display_name),
        )
    except imports.ImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return IssuerRead(id=issuer.id, display_name=issuer.display_name)


@router.get("/issuers", response_model=list[IssuerRead])
def get_issuers(session: SessionDependency) -> list[IssuerRead]:
    rows = session.scalars(
        select(Issuer).order_by(Issuer.display_name, Issuer.id).limit(500)
    )
    return [IssuerRead(id=row.id, display_name=row.display_name) for row in rows]


@router.get("/securities", response_model=list[SecurityRead])
def get_securities(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[SecurityRead]:
    rows = session.scalars(
        select(Security)
        .order_by(Security.display_ticker, Security.name, Security.id)
        .limit(limit)
    )
    return [_security_read(row) for row in rows]


@router.post(
    "/securities", response_model=SecurityRead, status_code=status.HTTP_201_CREATED
)
def post_security(request: Request, data: SecurityCreate) -> SecurityRead:
    try:
        security = run_database_unit(
            request.app.state.session_factory,
            lambda session: imports.security_create(session, data),
        )
    except imports.ImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _security_read(security)


@router.patch("/securities/{security_id}/issuer", response_model=SecurityRead)
def patch_security_issuer(
    request: Request, security_id: UUID, data: IssuerAssignment
) -> SecurityRead:
    try:
        security = run_database_unit(
            request.app.state.session_factory,
            lambda session: imports.assign_security_issuer(
                session,
                security_id,
                data.issuer_id,
                data.expected_issuer_id,
                data.reason,
            ),
        )
    except imports.ImportRevisionConflict as exc:
        raise HTTPException(
            status_code=409, detail="Issuer mapping changed; reload and review again."
        ) from exc
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _security_read(security)


@router.post(
    "/market-data/quotes", response_model=QuoteRead, status_code=status.HTTP_201_CREATED
)
def post_manual_quote(request: Request, data: QuoteCreate) -> QuoteRead:
    try:
        quote = run_database_unit(
            request.app.state.session_factory,
            lambda session: imports.record_manual_quote(session, data),
        )
    except imports.ImportBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return QuoteRead(
        id=quote.id,
        security_id=quote.security_id,
        as_of=quote.as_of,
        price=str(quote.price),
        currency=quote.currency,
        source=quote.source,
        quality_status=quote.quality_status,
    )


async def _read_bounded_request(request: Request, maximum: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdecimal() and int(declared) > maximum:
        raise HTTPException(
            status_code=413, detail="Document upload exceeds the configured size limit."
        )
    content = bytearray()
    async for block in request.stream():
        if len(content) + len(block) > maximum:
            raise HTTPException(
                status_code=413,
                detail="Document upload exceeds the configured size limit.",
            )
        content.extend(block)
    return bytes(content)


@router.post(
    "/imports/documents/positions/preview",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_brokerage_pdf_preview(
    request: Request,
    account_id: Annotated[UUID, Header(alias="X-Account-Id")],
    effective_date: Annotated[date, Header(alias="X-Effective-Date")],
    source_label: Annotated[str, Header(alias="X-Source-Label")],
    expected_account_revision: Annotated[
        int, Header(alias="X-Expected-Account-Revision")
    ],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    replace_existing: Annotated[bool, Header(alias="X-Replace-Existing")] = False,
) -> JobRead:
    if not request.app.state.job_worker_enabled:
        raise HTTPException(status_code=503, detail="Document worker is disabled.")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
    if content_type != "application/pdf":
        raise HTTPException(status_code=415, detail="Upload the statement as a PDF.")
    content = await _read_bounded_request(
        request, request.app.state.max_import_file_bytes
    )
    try:
        job_result = await asyncio.to_thread(
            jobs.enqueue_pdf_preview,
            request.app.state.session_factory,
            PrivateFileStore(request.app.state.private_file_root),
            content=content,
            filename=request.headers.get("x-file-name", "statement.pdf"),
            account_id=account_id,
            effective_date=effective_date,
            source_label=source_label,
            idempotency_key=idempotency_key,
            expected_account_revision=expected_account_revision,
            replace_existing=replace_existing,
            max_file_bytes=request.app.state.max_import_file_bytes,
            max_rows=request.app.state.max_import_rows,
            max_pages=request.app.state.max_pdf_pages,
            parser_timeout_seconds=request.app.state.pdf_parser_timeout_seconds,
            max_attempts=request.app.state.job_max_attempts,
        )
    except jobs.JobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except jobs.JobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return JobRead.model_validate(job_result)


@router.get("/documents/{document_id}", response_model=DocumentImportRead)
def get_document_import(
    document_id: UUID, session: SessionDependency
) -> DocumentImportRead:
    try:
        return DocumentImportRead.model_validate(
            documents.read_document_import(session, document_id)
        )
    except documents.DocumentNotFound as exc:
        raise HTTPException(
            status_code=404, detail="Document import not found."
        ) from exc


@router.get("/files/{file_id}/preview")
def get_private_file_preview(
    request: Request, file_id: UUID, session: SessionDependency
) -> Response:
    try:
        content, content_type, filename = documents.read_document_file(
            session,
            file_id,
            PrivateFileStore(request.app.state.private_file_root),
        )
    except documents.DocumentNotFound as exc:
        raise HTTPException(status_code=404, detail="Private file not found.") from exc
    except documents.DocumentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if content_type != "application/pdf":
        raise HTTPException(
            status_code=415, detail="This file cannot be previewed inline."
        )
    safe_name = quote(filename.replace("\r", "").replace("\n", ""), safe="")
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/imports/positions/preview", response_model=ImportCreated)
async def post_position_import_preview(
    request: Request,
    account_id: Annotated[UUID, Header(alias="X-Account-Id")],
    effective_date: Annotated[date, Header(alias="X-Effective-Date")],
    source_label: Annotated[str, Header(alias="X-Source-Label")],
    expected_account_revision: Annotated[
        int, Header(alias="X-Expected-Account-Revision")
    ],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    column_mapping: Annotated[str, Header(alias="X-Column-Mapping")],
    replace_existing: Annotated[bool, Header(alias="X-Replace-Existing")] = False,
) -> ImportCreated:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
    if content_type not in {"text/csv", "application/csv"}:
        raise HTTPException(status_code=415, detail="Upload the source as text/csv.")
    try:
        mapping = json.loads(column_mapping)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail="Column mapping must be valid JSON."
        ) from exc
    if not isinstance(mapping, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in mapping.items()
    ):
        raise HTTPException(
            status_code=422, detail="Column mapping must map field names to headers."
        )
    content = await _read_bounded_request(
        request, request.app.state.max_import_file_bytes
    )
    try:
        import_id, duplicate = imports.create_position_import(
            request.app.state.session_factory,
            PrivateFileStore(request.app.state.private_file_root),
            content=content,
            filename=request.headers.get("x-file-name", "positions.csv"),
            account_id=account_id,
            effective_date=effective_date,
            source_label=source_label,
            mapping=mapping,
            idempotency_key=idempotency_key,
            expected_account_revision=expected_account_revision,
            max_rows=request.app.state.max_import_rows,
            replace_existing=replace_existing,
        )
    except imports.InvalidCsv as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except imports.ImportAccountConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except imports.ImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    with request.app.state.session_factory() as session:
        attempt = session.get(ImportAttempt, import_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Import not found.")
        batch_count = session.scalar(
            select(func.count(ImportBatch.id)).where(
                ImportBatch.import_id == import_id,
                ImportBatch.purpose == "preview",
                ImportBatch.review_revision == 1,
            )
        )
        return ImportCreated(
            id=attempt.id,
            kind="positions",
            status=attempt.status,
            review_revision=attempt.review_revision,
            row_count=attempt.row_count,
            batch_count=int(batch_count or 0),
            duplicate=duplicate,
        )


@router.get("/imports/{import_id}", response_model=ImportReviewRead)
def get_import(import_id: UUID, session: SessionDependency) -> ImportReviewRead:
    try:
        return ImportReviewRead.model_validate(imports.read_import(session, import_id))
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail="Import not found.") from exc


@router.patch("/imports/{import_id}/rows/{row_id}", response_model=ImportRowRead)
def patch_import_row(
    request: Request,
    import_id: UUID,
    row_id: UUID,
    data: ImportRowCorrection,
) -> ImportRowRead:
    try:
        result = run_database_unit(
            request.app.state.session_factory,
            lambda session: imports.correct_import_row(
                session, import_id, row_id, data
            ),
        )
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except imports.ImportRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="Import changed; reload the review before correcting.",
        ) from exc
    except (imports.ImportConflict, imports.ImportBlocked) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportRowRead.model_validate(result)


@router.post("/imports/{import_id}/cancel", response_model=ImportCreated)
def post_cancel_import(
    request: Request, import_id: UUID, data: ImportAction
) -> ImportCreated:
    try:
        state = run_database_unit(
            request.app.state.session_factory,
            lambda session: imports.cancel_import(
                session,
                import_id,
                expected_revision=data.expected_review_revision,
                reason=data.reason,
            ),
        )
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail="Import not found.") from exc
    except imports.ImportRevisionConflict as exc:
        raise HTTPException(
            status_code=409, detail="Import changed; reload before cancelling."
        ) from exc
    except imports.ImportConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with request.app.state.session_factory() as session:
        attempt = session.get(ImportAttempt, import_id)
        if attempt is None:
            raise HTTPException(status_code=404, detail="Import not found.")
        return ImportCreated(
            id=attempt.id,
            kind="positions",
            status=state,
            review_revision=attempt.review_revision,
            row_count=attempt.row_count,
            batch_count=0,
            duplicate=False,
        )


@router.post("/imports/{import_id}/publish", response_model=PositionSnapshotRead)
def post_publish_import(
    request: Request, import_id: UUID, data: ImportAction
) -> PositionSnapshotRead:
    try:
        snapshot_id = imports.publish_position_import(
            request.app.state.session_factory,
            import_id,
            expected_review_revision=data.expected_review_revision,
        )
    except imports.ImportNotFound as exc:
        raise HTTPException(status_code=404, detail="Import not found.") from exc
    except (imports.ImportRevisionConflict, imports.ImportAccountConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (imports.ImportConflict, imports.ImportBlocked) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with request.app.state.session_factory() as session:
        snapshot = session.get(PositionSnapshot, snapshot_id)
        attempt = session.get(ImportAttempt, import_id)
        if snapshot is None or attempt is None or attempt.account_id is None:
            raise HTTPException(status_code=404, detail="Published snapshot not found.")
        return portfolio._as_read(
            snapshot, portfolio._snapshot_lines(session, snapshot_id)
        )


@router.put("/accounts/{account_id}/positions", response_model=PositionSnapshotRead)
def put_positions(
    request: Request, account_id: UUID, data: PositionReplace
) -> PositionSnapshotRead:
    try:
        return run_database_unit(
            request.app.state.session_factory,
            lambda session: portfolio.replace_positions(session, account_id, data),
        )
    except accounts.AccountNotFound as exc:
        raise HTTPException(status_code=404, detail="Account not found") from exc
    except portfolio.StaleRevision as exc:
        raise HTTPException(
            status_code=409,
            detail="Positions changed since they were loaded; reload before saving.",
        ) from exc
    except portfolio.ArchivedAccount as exc:
        raise HTTPException(
            status_code=409, detail="Archived accounts cannot be edited."
        ) from exc
    except portfolio.FutureObservation as exc:
        raise HTTPException(
            status_code=422,
            detail="Position observations cannot be dated in the future.",
        ) from exc
    except portfolio.UnknownSecurity as exc:
        raise HTTPException(
            status_code=422, detail="A selected security is not in the local catalog."
        ) from exc
    except portfolio.DuplicatePositionSecurity as exc:
        raise HTTPException(
            status_code=422, detail="A security can appear only once in a snapshot."
        ) from exc
    except portfolio.CurrencyMismatch as exc:
        raise HTTPException(
            status_code=422,
            detail="Position currency must match the selected security currency.",
        ) from exc
    except portfolio.CashPriceNotAllowed as exc:
        raise HTTPException(
            status_code=422,
            detail="Cash must be entered as a balance without a unit price.",
        ) from exc
    except portfolio.ValuationOutOfRange as exc:
        raise HTTPException(
            status_code=422,
            detail="The reported value exceeds the supported decimal precision.",
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="The position revision could not be saved; reload before retrying.",
        ) from exc
