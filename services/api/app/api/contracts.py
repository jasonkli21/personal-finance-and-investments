"""Public API contracts for accounts, local security lookup and positions."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    account_type: str = Field(min_length=1, max_length=40)
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("name", "account_type")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized


class ErrorResponse(BaseModel):
    detail: str


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    account_type: str | None = Field(default=None, min_length=1, max_length=40)
    base_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    active: bool | None = None

    @field_validator("name", "account_type")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_a_change(self) -> "AccountPatch":
        if not self.model_fields_set:
            raise ValueError("At least one account field must be provided")
        return self


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    account_type: str
    base_currency: str
    active: bool
    source_type: str


class SecurityRead(BaseModel):
    id: UUID
    security_type: str
    display_ticker: str | None
    name: str
    currency: str


class SecurityResolution(BaseModel):
    status: Literal["resolved", "ambiguous", "unknown"]
    matches: list[SecurityRead]


class PositionInput(BaseModel):
    security_id: UUID
    quantity: str = Field(max_length=40, pattern=r"^-?\d+(?:\.\d{1,10})?$")
    reported_price: str | None = Field(
        default=None, max_length=40, pattern=r"^\d+(?:\.\d{1,10})?$"
    )
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("quantity")
    @classmethod
    def quantity_precision(cls, value: str) -> str:
        if len(value.lstrip("-").split(".")[0]) > 18:
            raise ValueError("Quantity exceeds NUMERIC(28, 10) precision")
        return value

    @field_validator("reported_price")
    @classmethod
    def price_precision(cls, value: str | None) -> str | None:
        if value is not None and len(value.split(".")[0]) > 14:
            raise ValueError("Price exceeds NUMERIC(24, 10) precision")
        return value


class PositionReplace(BaseModel):
    expected_revision: int | None = Field(ge=0)
    effective_date: date
    positions: list[PositionInput] = Field(max_length=500)


class PositionLineRead(BaseModel):
    id: UUID
    security: SecurityRead
    quantity: str
    reported_price: str | None
    reported_value: str | None
    currency: str
    price_as_of: date | None
    source: str
    quality_status: str


class PositionSnapshotRead(BaseModel):
    id: UUID
    account_id: UUID
    effective_date: date
    revision: int
    source: str
    positions: list[PositionLineRead]


class PositionsEnvelope(BaseModel):
    snapshot: PositionSnapshotRead | None
    current_revision: int
