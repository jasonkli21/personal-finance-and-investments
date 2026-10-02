"""Finance-owned candidate boundary, not a frozen personal-AI wire contract.

Stage 1 has no AI consumer or HTTP transport. Later adapters must return
candidates for finance validation/review, never ORM entities or write commands.
"""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ExtractionRequest(BaseModel):
    """Bounded text and finance-selected schema identity; no paths or URLs."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_id: UUID
    schema_id: str = Field(min_length=1, max_length=100)
    schema_version: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=100_000, repr=False)


class ExtractionCandidate(BaseModel):
    """Untrusted fields; envelope validity does not establish financial validity.

    Future capability schemas must retain field evidence, raw values, as-of
    dates and quality. Decimal financial fields must arrive as strings and pass
    finance's own validators before the existing reviewed publication workflow.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_id: UUID
    schema_id: str = Field(min_length=1, max_length=100)
    schema_version: str = Field(min_length=1, max_length=40)
    fields: dict[str, JsonValue] = Field(repr=False)


class PersonalAIError(Exception):
    """Only stable finance-safe codes; never retain upstream content/errors."""

    def __init__(
        self,
        code: Literal["personal_ai_disabled", "personal_ai_invalid_response"],
    ) -> None:
        self.code = code
        super().__init__(code)


class PersonalAIClient(Protocol):
    async def extract(self, request: ExtractionRequest) -> ExtractionCandidate:
        """Return a candidate outside all database transactions and OCC retries."""
        ...


class DisabledPersonalAIClient:
    async def extract(self, request: ExtractionRequest) -> ExtractionCandidate:
        raise PersonalAIError("personal_ai_disabled")


class FakePersonalAIClient:
    """Explicit synthetic-test double; never selected by runtime settings."""

    def __init__(self, candidate: ExtractionCandidate) -> None:
        self._candidate = candidate.model_copy(deep=True)

    async def extract(self, request: ExtractionRequest) -> ExtractionCandidate:
        candidate = self._candidate
        if (
            candidate.source_id != request.source_id
            or candidate.schema_id != request.schema_id
            or candidate.schema_version != request.schema_version
        ):
            raise PersonalAIError("personal_ai_invalid_response")
        return candidate.model_copy(deep=True)
