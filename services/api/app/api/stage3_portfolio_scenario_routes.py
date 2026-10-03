"""Read-only hypothetical portfolio trade and exposure API."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from app.api.stage3_contracts import PortfolioScenarioRead, PortfolioScenarioRequest
from app.domains import portfolio_scenarios

router = APIRouter(prefix="/v1")


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


@router.post("/simulations/portfolio", response_model=PortfolioScenarioRead)
def simulate_portfolio(
    data: PortfolioScenarioRequest, session: SessionDependency
) -> PortfolioScenarioRead:
    try:
        result = portfolio_scenarios.simulate_portfolio(session, data)
        return PortfolioScenarioRead.model_validate(result)
    except portfolio_scenarios.PortfolioScenarioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
