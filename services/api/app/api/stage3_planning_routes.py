"""Read-only assumption-driven liquidity and purchase planning API."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api.stage3_contracts import PlanningScenarioRead, PlanningScenarioRequest
from app.domains import planning

router = APIRouter(prefix="/v1")


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


@router.post("/planning/scenarios", response_model=PlanningScenarioRead)
def create_planning_scenario(
    data: PlanningScenarioRequest, session: SessionDependency
) -> PlanningScenarioRead:
    try:
        result = planning.simulate_planning_scenario(session, data)
        return PlanningScenarioRead.model_validate(result)
    except planning.PlanningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
