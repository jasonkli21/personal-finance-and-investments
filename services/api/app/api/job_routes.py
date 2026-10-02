"""Safe status and cancellation routes for durable local jobs."""

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import ErrorResponse, JobRead
from app.db.transactions import run_database_unit
from app.domains.jobs import JobError, JobNotFound, cancel_job, read_job

router = APIRouter(
    prefix="/v1",
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
        409: {"model": ErrorResponse, "description": "Job state conflict"},
        503: {"model": ErrorResponse, "description": "Database unavailable"},
    },
)


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def _raise(exc: JobError) -> HTTPException:
    if isinstance(exc, JobNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: UUID, session: SessionDependency) -> JobRead:
    try:
        return JobRead.model_validate(read_job(session, job_id))
    except JobError as exc:
        raise _raise(exc) from exc


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def post_cancel_job(request: Request, job_id: UUID) -> JobRead:
    try:
        result = run_database_unit(
            request.app.state.session_factory,
            lambda session: cancel_job(session, job_id),
        )
        return JobRead.model_validate(result)
    except JobError as exc:
        raise _raise(exc) from exc
