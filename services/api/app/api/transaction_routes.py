"""Versioned transaction import, review, category and transfer routes."""

import asyncio
import json
from collections.abc import Iterator
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import (
    CategoryRuleCreate,
    CategoryRuleRead,
    ErrorResponse,
    SpendingCategoryCreate,
    SpendingCategoryRead,
    TransactionImportAction,
    TransactionImportCreated,
    TransactionImportReviewRead,
    TransactionManualCreate,
    TransactionPatch,
    TransactionRead,
    TransactionRowCorrection,
    TransactionRowRead,
    TransactionSplitRead,
    TransactionSplitsReplace,
    TransferCandidateRead,
    TransferCreate,
    TransferRead,
)
from app.db.models import FinancialTransaction, TransactionImport
from app.db.transactions import run_database_unit
from app.domains import transactions

router = APIRouter(
    prefix="/v1",
    responses={
        404: {"model": ErrorResponse, "description": "Requested resource not found"},
        409: {"model": ErrorResponse, "description": "Revision or identity conflict"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


async def _read_bounded_request(request: Request, maximum: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdecimal() and int(declared) > maximum:
        raise HTTPException(status_code=413, detail="Transaction CSV is too large.")
    content = bytearray()
    async for block in request.stream():
        if len(content) + len(block) > maximum:
            raise HTTPException(status_code=413, detail="Transaction CSV is too large.")
        content.extend(block)
    return bytes(content)


def _raise(exc: transactions.TransactionError) -> HTTPException:
    if isinstance(exc, transactions.TransactionNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, transactions.TransactionConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, transactions.TransactionBlocked):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/imports/transactions/preview",
    response_model=TransactionImportCreated,
    status_code=status.HTTP_201_CREATED,
)
async def post_transaction_import_preview(
    request: Request,
    account_id: Annotated[UUID, Header(alias="X-Account-Id")],
    source_label: Annotated[str, Header(alias="X-Source-Label")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    column_mapping: Annotated[str, Header(alias="X-Column-Mapping")],
    statement_start: Annotated[date | None, Header(alias="X-Statement-Start")] = None,
    statement_end: Annotated[date | None, Header(alias="X-Statement-End")] = None,
) -> TransactionImportCreated:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
    if content_type not in {"text/csv", "application/csv"}:
        raise HTTPException(status_code=415, detail="Upload transactions as text/csv.")
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
            status_code=422, detail="Column mapping must map fields to headers."
        )
    content = await _read_bounded_request(
        request, request.app.state.max_import_file_bytes
    )
    try:
        import_id, duplicate = await asyncio.to_thread(
            transactions.create_csv_import,
            request.app.state.session_factory,
            request.app.state.file_store,
            content=content,
            filename=request.headers.get("x-file-name", "transactions.csv"),
            account_id=account_id,
            source_label=source_label,
            idempotency_key=idempotency_key,
            mapping=mapping,
            statement_start=statement_start,
            statement_end=statement_end,
            max_rows=transactions.MAX_TRANSACTION_ROWS,
            max_file_bytes=request.app.state.max_import_file_bytes,
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc

    def read_result() -> TransactionImportCreated:
        with request.app.state.session_factory() as session:
            record = session.get(TransactionImport, import_id)
            if record is None:
                raise HTTPException(
                    status_code=404, detail="Transaction import not found."
                )
            return TransactionImportCreated(
                id=record.id,
                status=record.status,
                row_count=record.row_count,
                review_revision=record.review_revision,
                duplicate=duplicate,
            )

    return await asyncio.to_thread(read_result)


@router.get(
    "/transaction-imports/{import_id}",
    response_model=TransactionImportReviewRead,
)
def get_transaction_import(
    import_id: UUID, session: SessionDependency
) -> TransactionImportReviewRead:
    try:
        return TransactionImportReviewRead.model_validate(
            transactions.read_import(session, import_id)
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc


@router.patch(
    "/transaction-imports/{import_id}/rows/{row_id}",
    response_model=TransactionRowRead,
)
def patch_transaction_import_row(
    request: Request,
    import_id: UUID,
    row_id: UUID,
    data: TransactionRowCorrection,
) -> TransactionRowRead:
    try:
        result = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.correct_import_row(
                session, import_id, row_id, data
            ),
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    return TransactionRowRead.model_validate(result)


@router.post(
    "/transaction-imports/{import_id}/publish",
    response_model=TransactionImportCreated,
)
def post_publish_transaction_import(
    request: Request, import_id: UUID, data: TransactionImportAction
) -> TransactionImportCreated:
    try:
        state = transactions.publish_import(
            request.app.state.session_factory, import_id, data
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Transaction identity changed; reload review."
        ) from exc
    with request.app.state.session_factory() as session:
        record = session.get(TransactionImport, import_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Transaction import not found.")
        return TransactionImportCreated(
            id=record.id,
            status=state,
            row_count=record.row_count,
            review_revision=record.review_revision,
            duplicate=False,
        )


@router.post(
    "/transaction-imports/{import_id}/cancel",
    response_model=TransactionImportCreated,
)
def post_cancel_transaction_import(
    request: Request, import_id: UUID, data: TransactionImportAction
) -> TransactionImportCreated:
    try:
        state = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.cancel_import(session, import_id, data),
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    with request.app.state.session_factory() as session:
        record = session.get(TransactionImport, import_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Transaction import not found.")
        return TransactionImportCreated(
            id=record.id,
            status=state,
            row_count=record.row_count,
            review_revision=record.review_revision,
            duplicate=False,
        )


@router.get("/transactions", response_model=list[TransactionRead])
def get_transactions(
    session: SessionDependency,
    account_id: Annotated[UUID | None, Query()] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TransactionRead]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422, detail="Start date must not follow end date."
        )
    return [
        TransactionRead.model_validate(row)
        for row in transactions.list_transactions(
            session,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
    ]


@router.post(
    "/transactions/manual",
    response_model=TransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def post_manual_transaction(
    request: Request, data: TransactionManualCreate
) -> TransactionRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda db: transactions.create_manual_transaction(db, data),
        )
        with request.app.state.session_factory() as db:
            row = db.get(FinancialTransaction, row.id)
            if row is None:
                raise HTTPException(status_code=404, detail="Transaction not found.")
            result = transactions._transaction_read(db, row)
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Idempotency key was already used."
        ) from exc
    return TransactionRead.model_validate(result)


@router.patch("/transactions/{transaction_id}", response_model=TransactionRead)
def patch_transaction(
    request: Request, transaction_id: UUID, data: TransactionPatch
) -> TransactionRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.patch_transaction(
                session, transaction_id, data
            ),
        )
        with request.app.state.session_factory() as session:
            row = session.get(FinancialTransaction, row.id)
            if row is None:
                raise HTTPException(status_code=404, detail="Transaction not found.")
            result = transactions._transaction_read(session, row)
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    return TransactionRead.model_validate(result)


@router.get("/categories", response_model=list[SpendingCategoryRead])
def get_categories(session: SessionDependency) -> list[SpendingCategoryRead]:
    return [
        SpendingCategoryRead(id=row.id, slug=row.slug, display_name=row.display_name)
        for row in transactions.list_categories(session)
    ]


@router.post(
    "/categories",
    response_model=SpendingCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
def post_category(
    request: Request, data: SpendingCategoryCreate
) -> SpendingCategoryRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.create_category(session, data),
        )
    except transactions.TransactionConflict as exc:
        raise _raise(exc) from exc
    return SpendingCategoryRead(id=row.id, slug=row.slug, display_name=row.display_name)


@router.get("/category-rules", response_model=list[CategoryRuleRead])
def get_category_rules(session: SessionDependency) -> list[CategoryRuleRead]:
    return [
        CategoryRuleRead.model_validate(row)
        for row in transactions.list_category_rules(session)
    ]


@router.post(
    "/category-rules",
    response_model=CategoryRuleRead,
    status_code=status.HTTP_201_CREATED,
)
def post_category_rule(request: Request, data: CategoryRuleCreate) -> CategoryRuleRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.create_category_rule(session, data),
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    return CategoryRuleRead(
        id=row.id,
        merchant=row.normalized_merchant,
        normalized_merchant=row.normalized_merchant,
        category_id=row.category_id,
        priority=row.priority,
        version=row.version,
        active=row.active,
    )


@router.get(
    "/transactions/{transaction_id}/splits",
    response_model=list[TransactionSplitRead],
)
def get_transaction_splits(
    transaction_id: UUID, session: SessionDependency
) -> list[TransactionSplitRead]:
    return [
        TransactionSplitRead.model_validate(item)
        for item in transactions.read_splits(session, transaction_id)
    ]


@router.put(
    "/transactions/{transaction_id}/splits",
    response_model=list[TransactionSplitRead],
)
def put_transaction_splits(
    request: Request, transaction_id: UUID, data: TransactionSplitsReplace
) -> list[TransactionSplitRead]:
    try:
        run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.replace_splits(session, transaction_id, data),
        )
        with request.app.state.session_factory() as session:
            result = transactions.read_splits(session, transaction_id)
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    return [TransactionSplitRead.model_validate(item) for item in result]


@router.get("/transfers/candidates", response_model=list[TransferCandidateRead])
def get_transfer_candidates(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TransferCandidateRead]:
    return [
        TransferCandidateRead.model_validate(item)
        for item in transactions.transfer_candidates(session, limit=limit)
    ]


@router.post(
    "/transfers", response_model=TransferRead, status_code=status.HTTP_201_CREATED
)
def post_transfer(request: Request, data: TransferCreate) -> TransferRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.confirm_transfer(session, data),
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Transfer row is already linked."
        ) from exc
    return TransferRead(
        id=row.id,
        first_transaction_id=row.first_transaction_id,
        second_transaction_id=row.second_transaction_id,
        status=row.status,
        match_method=row.match_method,
        reason=row.reason,
        confirmed_at=row.confirmed_at,
    )


@router.post("/transfers/{transfer_id}/unlink", response_model=TransferRead)
def post_unlink_transfer(
    request: Request,
    transfer_id: UUID,
    reason: Annotated[str, Header(alias="X-Reason", min_length=1, max_length=500)],
) -> TransferRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: transactions.unlink_transfer(session, transfer_id, reason),
        )
    except transactions.TransactionError as exc:
        raise _raise(exc) from exc
    return TransferRead(
        id=row.id,
        first_transaction_id=row.first_transaction_id,
        second_transaction_id=row.second_transaction_id,
        status=row.status,
        match_method=row.match_method,
        reason=row.reason,
        confirmed_at=row.confirmed_at,
    )
