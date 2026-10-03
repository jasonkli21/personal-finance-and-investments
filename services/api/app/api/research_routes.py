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
    ResearchThesisNoteCreate,
    ResearchThesisNoteCreated,
    ResearchThesisNoteRead,
    ResearchWatchlistEventCreate,
    ResearchWatchlistEventRead,
    ResearchWatchlistRead,
)
from app.api.routes import SessionDependency
from app.db.models import Issuer
from app.db.transactions import run_database_unit
from app.domains import reports, research

router = APIRouter(prefix="/v1/research", tags=["research"])


class ResearchDocumentCreated(ResearchDocumentRead):
    duplicate: bool


class ReportedFactCreated(ReportedFactRead):
    duplicate: bool


class ResearchWatchlistEventCreated(ResearchWatchlistEventRead):
    pass


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


@router.get(
    "/issuers/{issuer_id}/thesis-notes", response_model=list[ResearchThesisNoteRead]
)
def get_thesis_notes(
    issuer_id: UUID, session: SessionDependency
) -> list[ResearchThesisNoteRead]:
    if not research.issuer_exists(session, issuer_id):
        raise HTTPException(status_code=404, detail="Issuer not found")
    return [
        ResearchThesisNoteRead.model_validate(row)
        for row in research.thesis_notes_for_issuer(session, issuer_id)
    ]


@router.post(
    "/thesis-notes",
    response_model=ResearchThesisNoteCreated,
    status_code=status.HTTP_201_CREATED,
)
def register_thesis_note(
    request: Request, data: ResearchThesisNoteCreate
) -> ResearchThesisNoteCreated:
    try:
        record, duplicate = run_database_unit(
            request.app.state.session_factory,
            lambda session: research.create_thesis_note(session, data),
        )
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research.ResearchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Thesis version changed") from exc
    return ResearchThesisNoteCreated(
        **ResearchThesisNoteRead.model_validate(record).model_dump(),
        duplicate=duplicate,
    )


@router.get("/watchlist", response_model=list[ResearchWatchlistRead])
def get_watchlist(session: SessionDependency) -> list[ResearchWatchlistRead]:
    return research.active_watchlist(session)


@router.get("/issuers/{issuer_id}/watchlist", response_model=ResearchWatchlistRead)
def get_issuer_watchlist(
    issuer_id: UUID, session: SessionDependency
) -> ResearchWatchlistRead:
    try:
        return research.watchlist_state(session, issuer_id)
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/issuers/{issuer_id}/watchlist/events",
    response_model=ResearchWatchlistEventCreated,
    status_code=status.HTTP_201_CREATED,
)
def post_watchlist_event(
    request: Request, issuer_id: UUID, data: ResearchWatchlistEventCreate
) -> ResearchWatchlistEventCreated:
    try:
        record, duplicate = run_database_unit(
            request.app.state.session_factory,
            lambda session: research.change_watchlist(session, issuer_id, data),
        )
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research.ResearchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Watchlist changed") from exc
    return ResearchWatchlistEventCreated.model_validate(
        {
            **ResearchWatchlistEventRead.model_validate(record).model_dump(),
            "duplicate": duplicate,
        }
    )


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
def create_research_run(
    request: Request, data: ResearchRunCreate, session: SessionDependency
) -> ResearchRunRead:
    issuer = session.get(Issuer, data.issuer_id)
    if issuer is None:
        raise HTTPException(status_code=404, detail="Issuer not found")
    try:
        context = None
        if data.portfolio_report_id is not None:
            try:
                report = reports.read(
                    session, request.app.state.file_store, data.portfolio_report_id
                )
            except reports.ReportNotFound as exc:
                raise HTTPException(
                    status_code=404, detail="Frozen portfolio report not found"
                ) from exc
            context = research.portfolio_context_from_report(
                report, issuer_id=issuer.id, issuer_name=issuer.display_name
            )
        thesis_note = research.thesis_note_for_run(
            session, data.thesis_note_id, data.issuer_id
        )
    except research.ResearchNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except research.ResearchConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    def create(database_session: Session) -> ResearchRunRead:
        run, _result, duplicate = research.create_baseline_run(
            database_session,
            data,
            portfolio_context=context,
            thesis_note=thesis_note,
        )
        return research.read_run(database_session, run.id, duplicate=duplicate)

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
