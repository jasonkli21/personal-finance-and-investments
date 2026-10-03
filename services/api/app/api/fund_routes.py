"Fund upload/review/history HTTP boundary; no provider IO inside DB retries."

import asyncio
import json
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from app.api.contracts import (
    FundCorrection,
    FundSnapshotRead,
    ImportAction,
    ImportCreated,
    ImportRowRead,
)
from app.api.routes import SessionDependency, _read_bounded_request
from app.db.models import FundSnapshot, ImportAttempt
from app.db.transactions import run_database_unit
from app.domains import funds, imports

router = APIRouter(prefix="/v1")


def error(exc: imports.ImportErrorBase) -> HTTPException:
    code = (
        404
        if isinstance(exc, imports.ImportNotFound)
        else 409
        if isinstance(exc, (imports.ImportConflict, imports.ImportRevisionConflict))
        else 422
    )
    return HTTPException(
        status_code=code,
        detail=str(exc) or "Import state changed; reload and review again",
    )


@router.post("/funds/{fund_id}/upload", response_model=ImportCreated)
async def upload(
    request: Request,
    fund_id: UUID,
    effective_date: Annotated[date, Header(alias="X-Effective-Date")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    source: Annotated[str, Header(alias="X-Source-Label")] = "User fund CSV",
    format_id: Annotated[str, Header(alias="X-Fund-Format")] = "manual",
    unit: Annotated[str, Header(alias="X-Weight-Unit")] = "percent",
    column_mapping: Annotated[str, Header(alias="X-Column-Mapping")] = "{}",
) -> ImportCreated:
    content = await _read_bounded_request(
        request, request.app.state.max_import_file_bytes
    )
    try:
        mapping = json.loads(column_mapping)
        if not isinstance(mapping, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
        ):
            raise imports.InvalidCsv("Mapping must be an object of header names")
        identifier, duplicate = await asyncio.to_thread(
            funds.preview,
            request.app.state.session_factory,
            request.app.state.file_store,
            content=content,
            filename=request.headers.get("x-file-name", "fund.csv"),
            fund_id=fund_id,
            as_of=effective_date,
            source=source,
            format_id=format_id,
            unit=unit,
            mapping=mapping,
            key=idempotency_key,
            max_rows=request.app.state.max_import_rows,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid mapping JSON") from exc
    except imports.ImportErrorBase as exc:
        raise error(exc) from exc

    def read_result() -> ImportCreated:
        with request.app.state.session_factory() as session:
            attempt = session.get(ImportAttempt, identifier)
            if attempt is None:
                raise HTTPException(status_code=404, detail="Fund import not found.")
            return ImportCreated(
                id=identifier,
                kind="fund",
                status=attempt.status,
                review_revision=attempt.review_revision,
                row_count=attempt.row_count,
                batch_count=attempt.batch_count,
                duplicate=duplicate,
            )

    return await asyncio.to_thread(read_result)


@router.patch("/fund-imports/{import_id}/rows/{row_id}", response_model=ImportRowRead)
def correction(
    request: Request, import_id: UUID, row_id: UUID, data: FundCorrection
) -> ImportRowRead:
    try:
        result = run_database_unit(
            request.app.state.session_factory,
            lambda session: funds.correct(
                session,
                import_id,
                row_id,
                revision=data.expected_review_revision,
                reason=data.reason,
                security_id=data.security_id,
                weight_value=data.weight,
                asset_type=data.asset_type,
            ),
        )
        return ImportRowRead.model_validate(result)
    except imports.ImportErrorBase as exc:
        raise error(exc) from exc


@router.post("/fund-imports/{import_id}/publish", response_model=FundSnapshotRead)
def publish(request: Request, import_id: UUID, data: ImportAction) -> FundSnapshotRead:
    try:
        identifier = funds.publish(
            request.app.state.session_factory, import_id, data.expected_review_revision
        )
    except imports.ImportErrorBase as exc:
        raise error(exc) from exc
    with request.app.state.session_factory() as session:
        snapshot = session.get(FundSnapshot, identifier)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Fund snapshot not found.")
        return FundSnapshotRead.model_validate(funds.snapshot_read(session, snapshot))


@router.get("/funds/{fund_id}/snapshots", response_model=list[FundSnapshotRead])
def history(fund_id: UUID, session: SessionDependency) -> list[FundSnapshotRead]:
    return [
        FundSnapshotRead.model_validate(funds.snapshot_read(session, s))
        for s in session.scalars(
            select(FundSnapshot)
            .where(
                FundSnapshot.fund_security_id == fund_id,
                FundSnapshot.status == "published",
            )
            .order_by(FundSnapshot.as_of.desc(), FundSnapshot.published_at.desc())
            .limit(100)
        )
    ]


@router.post("/funds/{fund_id}/refresh")
def refresh(fund_id: UUID) -> None:
    raise HTTPException(
        status_code=409,
        detail=(
            "Automatic retrieval is disabled pending verified access rights. "
            "Download official full holdings and upload them for review; "
            "last accepted data remains available."
        ),
    )
