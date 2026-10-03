"""Offline, user-entered SEC reference and reported-fact endpoints."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.research_contracts import (
    ReportedFactCreate,
    ReportedFactRead,
    ResearchDocumentCreate,
    ResearchDocumentRead,
)
from app.api.routes import SessionDependency
from app.db.transactions import run_database_unit
from app.domains import research

router = APIRouter(prefix="/v1/research", tags=["research"])


class ResearchDocumentCreated(ResearchDocumentRead):
    duplicate: bool


class ReportedFactCreated(ReportedFactRead):
    duplicate: bool


@router.post(
    "/documents",
    response_model=ResearchDocumentCreated,
    status_code=status.HTTP_201_CREATED,
)
def register_document(request: Request, data: ResearchDocumentCreate):
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
def register_fact(request: Request, data: ReportedFactCreate):
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
def get_documents(issuer_id: UUID, session: SessionDependency):
    rows = research.documents_for_issuer(session, issuer_id)
    if not rows and not research.issuer_exists(session, issuer_id):
        raise HTTPException(status_code=404, detail="Issuer not found")
    return [ResearchDocumentRead.model_validate(row) for row in rows]


@router.get("/documents/{document_id}/facts", response_model=list[ReportedFactRead])
def get_document_facts(document_id: UUID, session: SessionDependency):
    if not research.document_exists(session, document_id):
        raise HTTPException(status_code=404, detail="Research document not found")
    rows = research.facts_for_documents(session, [document_id])
    return [ReportedFactRead.model_validate(row) for row in rows]
