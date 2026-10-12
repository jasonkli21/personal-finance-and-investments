"""Finance-owned, read-only context contract for Personal AI.

This wire boundary is separate from ``PersonalAIClient.extract``. It contains
only bounded selected projections; it has no source-document or mutation DTOs.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

FINANCE_CONTEXT_SCHEMA: Literal["finance-context-read-v1"] = "finance-context-read-v1"
FINANCE_CONTEXT_PATH = "/v1/integrations/personal-ai/context"
type FinanceContextRecordEntityType = Literal[
    "account",
    "security",
    "position",
    "research_thesis",
    "research_fact",
    "discretionary_budget",
]
type FinanceContextSourceClass = Literal["domain_current", "external_research"]
type FinanceContextAuthority = Literal[
    "authoritative", "user_asserted", "derived", "external"
]
type FinanceSemanticClass = Literal[
    "observed", "calculated", "assumed", "ai_interpreted"
]
type FinanceSemanticState = Literal["known", "unknown", "conflict"]
FINANCE_CONTEXT_FIELDS = frozenset(
    {
        "account_summary",
        "balance_summary",
        "security_summary",
        "position_summary",
        "research_thesis",
        "research_fact",
        "permission_version",
        "amount",
        "currency",
        "period",
    }
)


class FinanceContextEntityReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    entity_type: Literal[
        "account",
        "security",
        "position",
        "issuer",
        "research_thesis",
        "research_fact",
        "portfolio",
        "discretionary_budget",
    ]
    entity_id: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def identifier_matches_entity(self) -> FinanceContextEntityReference:
        if self.entity_type == "portfolio":
            if self.entity_id != "all_active":
                raise ValueError("finance_context_portfolio_reference_invalid")
        else:
            try:
                UUID(self.entity_id)
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError("finance_context_entity_reference_invalid") from error
        return self


class FinanceContextReadRequest(BaseModel):
    """Exact requested projection. Owner identity is deliberately not a field."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["finance-context-read-v1"] = FINANCE_CONTEXT_SCHEMA
    application_id: Literal["finance"] = "finance"
    workspace_id: None = None
    operation: Literal["current", "verify"]
    purpose: Literal["personal_ai_context", "shopping_discretionary_budget"] = (
        "personal_ai_context"
    )
    destination_application_id: Literal["shopping"] | None = None
    entity_refs: tuple[FinanceContextEntityReference, ...] = Field(
        min_length=1, max_length=16
    )
    fields: tuple[str, ...] = Field(min_length=1, max_length=16)
    include_broader_context: bool = False
    max_results: int = Field(ge=1, le=32)
    max_bytes: int = Field(ge=512, le=32_768)

    @model_validator(mode="after")
    def enforce_scope_and_fields(self) -> FinanceContextReadRequest:
        if len(set(self.entity_refs)) != len(self.entity_refs):
            raise ValueError("finance_context_entity_references_not_unique")
        if (
            len(set(self.fields)) != len(self.fields)
            or not set(self.fields) <= FINANCE_CONTEXT_FIELDS
        ):
            raise ValueError("finance_context_fields_invalid")
        portfolios = [ref for ref in self.entity_refs if ref.entity_type == "portfolio"]
        budget_refs = [
            ref for ref in self.entity_refs if ref.entity_type == "discretionary_budget"
        ]
        budget_fields = {"amount", "currency", "period"}
        if budget_refs or set(self.fields) & budget_fields:
            expected_fields = (
                ("permission_version",)
                if self.operation == "verify"
                else ("amount", "currency", "period")
            )
            if (
                len(budget_refs) != 1
                or len(self.entity_refs) != 1
                or self.fields != expected_fields
                or self.purpose != "shopping_discretionary_budget"
                or self.destination_application_id != "shopping"
                or self.include_broader_context
            ):
                raise ValueError("finance_context_budget_export_scope_invalid")
        elif (
            self.purpose != "personal_ai_context"
            or self.destination_application_id is not None
        ):
            raise ValueError("finance_context_destination_scope_invalid")
        if self.include_broader_context != bool(portfolios):
            raise ValueError(
                "finance_context_broader_scope_requires_explicit_selection"
            )
        if self.operation == "verify" and self.fields != ("permission_version",):
            raise ValueError("finance_context_verify_projection_invalid")
        if self.operation == "current" and "permission_version" in self.fields:
            raise ValueError("finance_context_permission_field_reserved")
        if self.operation == "verify":
            if self.include_broader_context or any(
                reference.entity_type == "portfolio" for reference in self.entity_refs
            ):
                raise ValueError("finance_context_verify_broad_scope_invalid")
        else:
            reference_types = {reference.entity_type for reference in self.entity_refs}
            if "portfolio" in reference_types:
                if reference_types != {"portfolio"} or set(self.fields) - {
                    "account_summary",
                    "balance_summary",
                    "security_summary",
                    "position_summary",
                }:
                    raise ValueError("finance_context_broad_scope_invalid")
            else:
                expected_types: set[str] = set()
                if set(self.fields) & {"amount", "currency", "period"}:
                    expected_types.add("discretionary_budget")
                if set(self.fields) & {"account_summary", "balance_summary"}:
                    expected_types.add("account")
                if "security_summary" in self.fields:
                    expected_types.add("security")
                if "position_summary" in self.fields:
                    expected_types.update({"account", "security"})
                if "research_thesis" in self.fields:
                    expected_types.add("issuer")
                if "research_fact" in self.fields:
                    expected_types.add("research_fact")
                if reference_types != expected_types:
                    raise ValueError("finance_context_selection_scope_invalid")
        return self


class FinanceSemanticValue(BaseModel):
    """One financial value with its domain meaning and source metadata."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    semantic_class: FinanceSemanticClass
    value: JsonValue
    state: FinanceSemanticState = "known"
    unit: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    as_of: str | None = Field(default=None, max_length=40)
    source_identity: str = Field(min_length=1, max_length=120)
    source_version: str = Field(min_length=1, max_length=120)
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=8)
    calculation_version: str | None = Field(default=None, max_length=80)
    quality: str = Field(min_length=1, max_length=80)
    uncertainty: str | None = Field(default=None, max_length=160)
    authority: Literal[
        "authoritative", "user_asserted", "derived", "external", "unknown"
    ]
    sensitivity: Literal["personal", "sensitive", "restricted"]


class FinanceContextSourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["record", "evidence"]
    reference_id: str = Field(min_length=1, max_length=200)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class FinanceContextPermissionDependency(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    permission_id: str = Field(min_length=1, max_length=240)
    version: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=160)


class FinanceContextFieldSensitivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    field: str = Field(min_length=1, max_length=80)
    sensitivity: Literal["personal", "sensitive", "restricted"]


class FinanceContextRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    entity_type: FinanceContextRecordEntityType
    entity_id: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=200)
    source_version: str = Field(min_length=1, max_length=120)
    source_class: FinanceContextSourceClass
    authority: FinanceContextAuthority
    observed_at: str | None = Field(default=None, max_length=40)
    effective_at: str | None = Field(default=None, max_length=40)
    sensitivity: Literal["personal", "sensitive", "restricted"]
    payload: dict[str, dict[str, FinanceSemanticValue]] = Field(
        default_factory=dict, max_length=16
    )
    source_refs: tuple[FinanceContextSourceReference, ...] = Field(
        min_length=1, max_length=8
    )
    permission_dependencies: tuple[FinanceContextPermissionDependency, ...] = Field(
        min_length=1, max_length=8
    )
    field_sensitivity: tuple[FinanceContextFieldSensitivity, ...] = Field(
        default=(), max_length=16
    )

    @field_validator("payload")
    @classmethod
    def payload_is_bounded_semantic_data(
        cls, value: dict[str, dict[str, FinanceSemanticValue]]
    ) -> dict[str, dict[str, FinanceSemanticValue]]:
        if any(
            len(fields) > 16
            or any(
                not field
                or len(field) > 80
                or not field[0].islower()
                or not all(
                    char.islower() or char.isdigit() or char == "_" for char in field
                )
                for field in fields
            )
            for fields in value.values()
        ):
            raise ValueError("finance_context_semantic_payload_invalid")
        return value


class FinanceContextReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["finance-context-read-v1"] = FINANCE_CONTEXT_SCHEMA
    application_id: Literal["finance"] = "finance"
    workspace_id: None = None
    items: tuple[FinanceContextRecord, ...] = Field(default=(), max_length=32)
