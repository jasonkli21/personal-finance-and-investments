"""Finance-owned immutable Shopping commands resolved from current consented budgets."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.service import PrincipalContext
from app.config import Settings
from app.db.models import DelegatedSourceCommand as CommandRow
from app.db.models import MonthlyDiscretionaryBudget
from app.domains.finance_context import _monthly_budget_source_version
from app.integrations.task_auth import active_task_principal
from app.integrations.task_wire import DelegatedSourceCommand


class BudgetTaskChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command_id: UUID
    period: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    expected_budget_revision: int = Field(strict=True, ge=1)
    context_choice_id: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    shopping_project_id: UUID
    expected_project_revision: int = Field(strict=True, ge=1, le=10**18 - 1)


def create_budget_command(
    session: Session,
    settings: Settings,
    principal: PrincipalContext,
    choice: BudgetTaskChoice,
) -> DelegatedSourceCommand:
    if settings.task_settings is None:
        raise HTTPException(404, "not_found")
    owner = active_task_principal(
        session, settings, principal.issuer, principal.subject
    )
    if session.get_bind().dialect.name == "postgresql":
        # Serialize the immutable command key before observing/creating it.
        # Concurrent identical submissions must replay, not race a unique INSERT.
        lock_key = int.from_bytes(
            sha256(choice.command_id.bytes).digest()[:8], "big", signed=True
        )
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    existing = session.get(CommandRow, choice.command_id)
    if existing is not None:
        if existing.principal_id != owner.id:
            raise HTTPException(409, "command_idempotency_conflict")
        command = DelegatedSourceCommand.model_validate(existing.command)
        budget = session.get(MonthlyDiscretionaryBudget, UUID(command.source_entity_id))
        if (
            budget is None
            or budget.period != choice.period
            or budget.revision != choice.expected_budget_revision
            or command.target_entity_id != choice.shopping_project_id
            or command.expected_domain_version != str(choice.expected_project_revision)
            or command.context_choice_id != choice.context_choice_id
        ):
            raise HTTPException(409, "command_idempotency_conflict")
        return command
    budget = session.scalar(
        select(MonthlyDiscretionaryBudget)
        .where(MonthlyDiscretionaryBudget.period == choice.period)
        .with_for_update()
    )
    if (
        budget is None
        or not budget.share_with_shopping
        or budget.revision != choice.expected_budget_revision
    ):
        raise HTTPException(409, "budget_consent_or_revision_changed")
    command = DelegatedSourceCommand(
        source_application_id="finance",
        command_id=choice.command_id,
        context_choice_id=choice.context_choice_id,
        source_entity_type="discretionary_budget",
        source_entity_id=str(budget.id),
        expected_source_version=_monthly_budget_source_version(budget),
        target_entity_id=choice.shopping_project_id,
        expected_domain_version=str(choice.expected_project_revision),
        operation_id="project.set_budget",
        operation_version=1,
        operation_contract_fingerprint=settings.task_settings.operation_fingerprint,
        payload_schema_id="shopping-budget-allocation-v1",
        payload={
            "amount": format(budget.amount, ".2f"),
            "currency": budget.currency,
        },
        rationale=(
            f"Use the explicitly shared discretionary budget for {budget.period}."
        ),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    session.add(
        CommandRow(
            command_id=command.command_id,
            principal_id=owner.id,
            command=command.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    return command
