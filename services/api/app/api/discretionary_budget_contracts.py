"""Canonical monthly discretionary budget API contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Period = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
Amount = Annotated[str, Field(max_length=18, pattern=r"^\d{1,12}(?:\.\d{1,2})?$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class MonthlyDiscretionaryBudgetWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=0)
    amount: Amount
    currency: Currency
    share_with_shopping: bool = False

    @field_validator("amount")
    @classmethod
    def amount_is_finite_and_bounded(cls, value: str) -> str:
        amount = Decimal(value)
        if not amount.is_finite() or amount > Decimal("999999999999.99"):
            raise ValueError("budget_amount_out_of_range")
        return format(amount, ".2f")


class MonthlyDiscretionaryBudgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period: Period
    amount: Decimal
    currency: str
    share_with_shopping: bool
    revision: int
    updated_at: datetime
