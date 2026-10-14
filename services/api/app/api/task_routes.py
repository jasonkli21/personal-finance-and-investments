"""Finance-owned command creation and explicit user-controlled mutation lifecycle."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.service import PrincipalContext
from app.db.models import DelegatedSourceCommand as CommandRow
from app.db.models import MonthlyDiscretionaryBudget
from app.domains.finance_context import _monthly_budget_source_version
from app.domains.shopping_commands import BudgetTaskChoice, create_budget_command
from app.integrations.task_auth import active_task_principal, verify_task_user
from app.integrations.task_client import (
    TaskControlClient,
    TaskControlRejected,
    TaskControlUnavailable,
)
from app.integrations.task_control import SourceTaskStatus as ShoppingTaskStatus
from app.integrations.task_control import source_task_status
from app.integrations.task_wire import (
    COMMAND_READ_FINGERPRINT,
    DelegatedCommandRead,
    DelegatedSourceCommand,
)

router = APIRouter(tags=["Delegated Shopping tasks"])


class TaskConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_id: UUID
    binding: str = Field(pattern=r"^[0-9a-f]{64}$")


def _principal(request: Request) -> PrincipalContext:
    settings = request.app.state.settings
    principal = getattr(request.state, "principal", None)
    if settings.task_settings is None:
        raise HTTPException(404, "not_found")
    now = int(time.time())
    if (
        not isinstance(principal, PrincipalContext)
        or principal.authenticated_at is None
        or now - principal.authenticated_at > 300
        or principal.authenticated_at > now + 30
    ):
        raise HTTPException(401, "recent_authentication_required")
    return principal


def _command(
    session: Session, request: Request, principal: PrincipalContext, command_id: UUID
) -> CommandRow:
    owner = active_task_principal(
        session, request.app.state.settings, principal.issuer, principal.subject
    )
    row = session.get(CommandRow, command_id)
    if row is None or row.principal_id != owner.id:
        raise HTTPException(404, "command_not_found")
    return row


@router.post(
    "/v1/finance/shopping-tasks/commands",
    response_model=DelegatedSourceCommand,
    status_code=201,
)
def create_command(
    request: Request, choice: BudgetTaskChoice
) -> DelegatedSourceCommand:
    principal = _principal(request)
    with request.app.state.session_factory() as session, session.begin():
        return create_budget_command(
            session, request.app.state.settings, principal, choice
        )


@router.post(
    "/internal/personal-ai/commands/read",
    response_model=DelegatedSourceCommand,
    include_in_schema=False,
)
async def read_command(request: Request) -> DelegatedSourceCommand:
    if request.app.state.settings.task_settings is None:
        raise HTTPException(404, "not_found")
    raw = bytearray()
    try:
        async with asyncio.timeout(3):
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw) > 8192:
                    raise HTTPException(413, "task_request_too_large")
    except TimeoutError as error:
        raise HTTPException(408, "task_request_timeout") from error

    try:
        body = DelegatedCommandRead.model_validate_json(raw)
        if (
            body.destination_application_id != "finance"
            or body.workspace_id is not None
        ):
            raise ValueError
        if (
            request.headers.get("x-task-contract-fingerprint")
            != COMMAND_READ_FINGERPRINT
        ):
            raise ValueError
    except ValueError as error:
        raise HTTPException(409, "task_contract_unsupported") from error
    identity = await run_in_threadpool(
        verify_task_user, request, body.model_dump(mode="json")
    )
    with request.app.state.session_factory() as session:
        owner = active_task_principal(
            session, request.app.state.settings, identity.issuer, identity.subject
        )
        row = session.get(CommandRow, body.command_id)
        if row is None or row.principal_id != owner.id:
            raise HTTPException(404, "command_not_found")
        command = DelegatedSourceCommand.model_validate(row.command)
        budget = session.get(MonthlyDiscretionaryBudget, UUID(command.source_entity_id))
        if (
            budget is None
            or not budget.share_with_shopping
            or _monthly_budget_source_version(budget) != command.expected_source_version
        ):
            raise HTTPException(409, "budget_consent_or_revision_changed")
        return command


def _public_status(
    result: dict[str, Any], expected_proposal_id: UUID | None = None
) -> ShoppingTaskStatus:
    try:
        return source_task_status(result, expected_proposal_id=expected_proposal_id)
    except TaskControlUnavailable as error:
        raise HTTPException(503, "task_control_response_invalid") from error


@router.get("/v1/finance/shopping-tasks/capabilities")
def capabilities(request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    principal = getattr(request.state, "principal", None)
    auth_time = (
        principal.authenticated_at if isinstance(principal, PrincipalContext) else None
    )
    recent = auth_time is not None and -30 <= int(time.time()) - auth_time <= 300
    return {
        "enabled": settings.task_settings is not None,
        "recent_authentication": recent,
    }


def _relay(
    request: Request,
    principal: PrincipalContext,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = getattr(
        request.app.state, "task_control_client", None
    ) or TaskControlClient(request.app.state.settings.task_settings)
    try:
        return client.request(principal, method, path, body)
    except TaskControlRejected as error:
        raise HTTPException(error.status, "task_control_rejected") from error
    except TaskControlUnavailable as error:
        raise HTTPException(503, "task_control_unavailable") from error


@router.get("/v1/finance/shopping-tasks/choices")
def choices(request: Request) -> dict[str, Any]:
    return _relay(request, _principal(request), "GET", "/v1/federation/grants/choices")


@router.post(
    "/v1/finance/shopping-tasks/commands/{command_id}/submit",
    response_model=ShoppingTaskStatus,
)
def submit(request: Request, command_id: UUID) -> ShoppingTaskStatus:
    principal = _principal(request)
    with request.app.state.session_factory() as session:
        _command(session, request, principal, command_id)
    result = _relay(
        request,
        principal,
        "POST",
        "/v1/mutations/commands",
        {"source_application_id": "finance", "command_id": str(command_id)},
    )
    try:
        proposal_id = UUID(result["proposal"]["proposal_id"])
        provenance = result["proposal"]["intent"]["producer"]
        if provenance.get("source_application_id") != "finance" or provenance.get(
            "command_id"
        ) != str(command_id):
            raise ValueError
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, "task_control_response_invalid") from error
    with request.app.state.session_factory() as session, session.begin():
        row = _command(session, request, principal, command_id)
        if row.proposal_id is not None and row.proposal_id != proposal_id:
            raise HTTPException(409, "command_proposal_conflict")
        row.proposal_id = proposal_id
    return _public_status(result)


@router.post(
    "/v1/finance/shopping-tasks/commands/{command_id}/{action}",
    response_model=ShoppingTaskStatus,
)
def control(
    request: Request,
    command_id: UUID,
    action: Literal["validate", "confirm", "apply", "reconcile"],
    confirmation: TaskConfirmation | None = None,
) -> ShoppingTaskStatus:
    principal = _principal(request)
    if (action in {"confirm", "apply"}) != (confirmation is not None):
        raise HTTPException(422, "task_confirmation_required")
    with request.app.state.session_factory() as session:
        row = _command(session, request, principal, command_id)
        if row.proposal_id is None:
            raise HTTPException(409, "command_not_submitted")
        proposal_id = row.proposal_id
    return _public_status(
        _relay(
            request,
            principal,
            "POST",
            f"/v1/mutations/{proposal_id}/{action}",
            confirmation.model_dump(mode="json") if confirmation is not None else None,
        ),
        expected_proposal_id=proposal_id,
    )


@router.get(
    "/v1/finance/shopping-tasks/commands/{command_id}",
    response_model=ShoppingTaskStatus,
)
def status(request: Request, command_id: UUID) -> ShoppingTaskStatus:
    principal = _principal(request)
    with request.app.state.session_factory() as session:
        row = _command(session, request, principal, command_id)
        if row.proposal_id is None:
            raise HTTPException(409, "command_not_submitted")
        proposal_id = row.proposal_id
    return _public_status(
        _relay(request, principal, "GET", f"/v1/mutations/{proposal_id}"),
        expected_proposal_id=proposal_id,
    )
