"""Offline, user-entered SEC reference and reported-fact endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.research_contracts import (
    FactComparisonCreate,
    FactComparisonRead,
    ReportedFactCreate,
    ReportedFactRead,
    ResearchCompanyRead,
    ResearchDocumentCreate,
    ResearchDocumentRead,
    ResearchRunCreate,
    ResearchRunRead,
)
from app.api.routes import SessionDependency
from app.db.transactions import run_database_unit
from app.domains import research

router = APIRouter(prefix="/v1/research", tags=["research"])


class ResearchDocumentCreated(ResearchDocumentRead):
    duplicate: bool


class ReportedFactCreated(ReportedFactRead):
    duplicate: bool


@router.get("/issuers/{issuer_id}", response_model=ResearchCompanyRead)
def get_company_research(
    issuer_id: UUID, session: SessionDependency
) -> ResearchCompanyRead:
    try:
        return research.company_research(session, issuer_id)
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/documents",
    response_model=ResearchDocumentCreated,
    status_code=status.HTTP_201_CREATED,
)
def register_document(
    request: Request, data: ResearchDocumentCreate
) -> ResearchDocumentCreated:
    try:
        record, duplicate = run_database_unit(
            request.app.state.session_factory,
            lambda session: research.create_document(session, data),
        )
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research.ResearchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Filing accession already exists"
        ) from exc
    return ResearchDocumentCreated.model_validate(
        {
            **ResearchDocumentRead.model_validate(record).model_dump(),
            "duplicate": duplicate,
        }
    )


@router.post(
    "/facts",
    response_model=ReportedFactCreated,
    status_code=status.HTTP_201_CREATED,
)
def register_fact(request: Request, data: ReportedFactCreate) -> ReportedFactCreated:
    try:
        record, duplicate = run_database_unit(
            request.app.state.session_factory,
            lambda session: research.create_fact(session, data),
        )
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research.ResearchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Fact idempotency key already exists"
        ) from exc
    return ReportedFactCreated.model_validate(
        {
            **ReportedFactRead.model_validate(record).model_dump(),
            "duplicate": duplicate,
        }
    )


@router.get("/issuers/{issuer_id}/documents", response_model=list[ResearchDocumentRead])
def get_documents(
    issuer_id: UUID, session: SessionDependency
) -> list[ResearchDocumentRead]:
    rows = research.documents_for_issuer(session, issuer_id)
    if not rows and not research.issuer_exists(session, issuer_id):
        raise HTTPException(status_code=404, detail="Issuer not found")
    return [ResearchDocumentRead.model_validate(row) for row in rows]


@router.get("/documents/{document_id}/facts", response_model=list[ReportedFactRead])
def get_document_facts(
    document_id: UUID, session: SessionDependency
) -> list[ReportedFactRead]:
    if not research.document_exists(session, document_id):
        raise HTTPException(status_code=404, detail="Research document not found")
    rows = research.facts_for_documents(session, [document_id])
    return [ReportedFactRead.model_validate(row) for row in rows]


@router.post("/comparisons", response_model=FactComparisonRead)
def compare_research_facts(
    data: FactComparisonCreate, session: SessionDependency
) -> FactComparisonRead:
    try:
        result = research.compare_facts(session, data)
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FactComparisonRead.model_validate(result)


@router.post(
    "/runs",
    response_model=ResearchRunRead,
    status_code=status.HTTP_201_CREATED,
)
def create_research_run(request: Request, data: ResearchRunCreate) -> ResearchRunRead:
    def create(session: Session) -> ResearchRunRead:
        run, _result, duplicate = research.create_baseline_run(session, data)
        return research.read_run(session, run.id, duplicate=duplicate)

    try:
        return run_database_unit(request.app.state.session_factory, create)
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research.ResearchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="Research run conflicts with an existing request"
        ) from exc


@router.get("/runs/{run_id}", response_model=ResearchRunRead)
def get_research_run(run_id: UUID, session: SessionDependency) -> ResearchRunRead:
    try:
        return research.read_run(session, run_id)
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
