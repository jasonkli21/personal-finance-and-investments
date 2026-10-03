"""Reviewed source-backed tax-lot import and adjustment routes."""

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.api.routes import SessionDependency, _read_bounded_request
from app.api.stage3_contracts import (
    TaxLotAdjustmentCreate,
    TaxLotAdjustmentRead,
    TaxLotImportCorrection,
    TaxLotImportCreated,
    TaxLotImportPublish,
    TaxLotImportReviewRead,
    TaxLotRead,
)
from app.db.models import TaxLotImport
from app.db.transactions import run_database_unit
from app.domains import tax

router = APIRouter(prefix="/v1")


def _raise_tax(exc: tax.TaxError) -> HTTPException:
    detail = str(exc)
    lowered = detail.casefold()
    code = (
        404
        if "not found" in lowered
        else 409
        if any(
            token in lowered
            for token in ("revision changed", "idempotency key", "already")
        )
        else 422
    )
    return HTTPException(status_code=code, detail=detail)


@router.post(
    "/imports/tax-lots/preview",
    response_model=TaxLotImportCreated,
    status_code=201,
)
async def preview_tax_lots(
    request: Request,
    account_id: Annotated[UUID, Header(alias="X-Account-Id")],
    source_label: Annotated[str, Header(alias="X-Source-Label")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    column_mapping: Annotated[str, Header(alias="X-Column-Mapping")] = "{}",
) -> TaxLotImportCreated:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].casefold()
    if content_type not in {"text/csv", "application/csv", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Upload the lot file as CSV.")
    content = await _read_bounded_request(
        request, request.app.state.max_import_file_bytes
    )
    try:
        mapping = json.loads(column_mapping)
        if not isinstance(mapping, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in mapping.items()
        ):
            raise tax.TaxError("Column mapping must map field names to CSV headers.")
        identifier, duplicate = await run_in_threadpool(
            tax.create_csv_import,
            request.app.state.session_factory,
            request.app.state.file_store,
            content=content,
            filename=request.headers.get("x-file-name", "tax-lots.csv"),
            account_id=account_id,
            source_label=source_label,
            idempotency_key=idempotency_key,
            mapping=mapping,
            max_file_bytes=request.app.state.max_import_file_bytes,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid column mapping JSON."
        ) from exc
    except tax.TaxError as exc:
        raise _raise_tax(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A matching tax-lot import was created concurrently.",
        ) from exc
    with request.app.state.session_factory() as session:
        record = session.get(TaxLotImport, identifier)
        assert record is not None
        return TaxLotImportCreated(
            id=record.id,
            status=record.status,
            row_count=record.row_count,
            review_revision=record.review_revision,
            duplicate=duplicate,
        )


@router.get("/tax-lot-imports/{import_id}", response_model=TaxLotImportReviewRead)
def read_tax_lot_import(
    import_id: UUID, session: SessionDependency
) -> TaxLotImportReviewRead:
    try:
        return TaxLotImportReviewRead.model_validate(
            tax.read_import(session, import_id)
        )
    except tax.TaxError as exc:
        raise _raise_tax(exc) from exc


@router.patch(
    "/tax-lot-imports/{import_id}/rows/{row_id}",
    response_model=TaxLotImportReviewRead,
)
def correct_tax_lot_row(
    request: Request,
    import_id: UUID,
    row_id: UUID,
    data: TaxLotImportCorrection,
) -> TaxLotImportReviewRead:
    try:
        run_database_unit(
            request.app.state.session_factory,
            lambda session: tax.correct_import_row(session, import_id, row_id, data),
        )
        with request.app.state.session_factory() as session:
            return TaxLotImportReviewRead.model_validate(
                tax.read_import(session, import_id)
            )
    except tax.TaxError as exc:
        raise _raise_tax(exc) from exc


@router.post(
    "/tax-lot-imports/{import_id}/publish",
    response_model=TaxLotImportReviewRead,
)
def publish_tax_lot_import(
    request: Request,
    import_id: UUID,
    data: TaxLotImportPublish,
) -> TaxLotImportReviewRead:
    try:
        run_database_unit(
            request.app.state.session_factory,
            lambda session: tax.publish_import(session, import_id, data),
        )
        with request.app.state.session_factory() as session:
            return TaxLotImportReviewRead.model_validate(
                tax.read_import(session, import_id)
            )
    except tax.TaxError as exc:
        raise _raise_tax(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A tax lot was published concurrently. Reload and review.",
        ) from exc


@router.get("/tax-lots", response_model=list[TaxLotRead])
def list_tax_lots(
    session: SessionDependency,
    account_id: Annotated[UUID | None, Query()] = None,
    security_id: Annotated[UUID | None, Query()] = None,
    quality_status: Annotated[Literal["reported", "incomplete"] | None, Query()] = None,
) -> list[TaxLotRead]:
    try:
        return [
            TaxLotRead.model_validate(row)
            for row in tax.list_lots(
                session,
                account_id=account_id,
                security_id=security_id,
                quality_status=quality_status,
            )
        ]
    except tax.TaxError as exc:
        raise _raise_tax(exc) from exc


@router.post(
    "/tax-lots/{lot_id}/adjustments",
    response_model=TaxLotAdjustmentRead,
    status_code=201,
)
def add_tax_lot_adjustment(
    request: Request, lot_id: UUID, data: TaxLotAdjustmentCreate
) -> TaxLotAdjustmentRead:
    try:
        row = run_database_unit(
            request.app.state.session_factory,
            lambda session: tax.create_adjustment(session, lot_id, data),
        )
    except tax.TaxError as exc:
        raise _raise_tax(exc) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="A lot adjustment was added concurrently."
        ) from exc
    return TaxLotAdjustmentRead(
        id=row.id,
        tax_lot_id=row.tax_lot_id,
        adjustment_type=row.adjustment_type,
        quantity_delta=str(row.quantity_delta)
        if row.quantity_delta is not None
        else None,
        basis_delta=str(row.basis_delta) if row.basis_delta is not None else None,
        basis_currency=row.basis_currency,
        effective_date=row.effective_date,
        source_label=row.source_label,
        reason=row.reason,
        evidence_ref=row.evidence_ref,
        created_at=row.created_at,
    )
