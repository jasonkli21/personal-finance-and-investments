"""No-network candidate boundary and fail-closed runtime configuration."""

import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.contracts import PositionInput
from app.config import load_settings
from app.integrations.personal_ai import (
    DisabledPersonalAIClient,
    ExtractionCandidate,
    ExtractionRequest,
    FakePersonalAIClient,
    PersonalAIClient,
    PersonalAIError,
)
from app.main import create_app


def request() -> ExtractionRequest:
    return ExtractionRequest(
        source_id=uuid4(),
        schema_id="synthetic.positions",
        schema_version="test/1",
        text="Synthetic account: quantity unclear",
    )


def test_disabled_client_and_default_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PERSONAL_AI_ENABLED", raising=False)
    assert load_settings().personal_ai_enabled is False
    app = create_app()
    try:
        client: PersonalAIClient = app.state.personal_ai_client
        assert isinstance(client, DisabledPersonalAIClient)
        with pytest.raises(PersonalAIError) as error:
            asyncio.run(client.extract(request()))
        assert error.value.code == "personal_ai_disabled"
        assert str(error.value) == "personal_ai_disabled"
        assert not any("personal-ai" in path for path in app.openapi()["paths"])
    finally:
        app.state.database_engine.dispose()


@pytest.mark.parametrize("value", ["true", "TRUE", "yes", "1"])
def test_enabling_or_malformed_flag_fails_before_transport(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PERSONAL_AI_ENABLED", value)
    monkeypatch.setenv("PERSONAL_AI_BASE_URL", "https://unauthorized.example")
    with pytest.raises(ValueError, match="PERSONAL_AI_ENABLED"):
        create_app()


def test_fake_candidate_stays_untrusted_and_does_not_leak_content() -> None:
    data = request()
    candidate = ExtractionCandidate(
        source_id=data.source_id,
        schema_id=data.schema_id,
        schema_version=data.schema_version,
        fields={
            "security_id": str(uuid4()),
            "quantity": "invented quantity",
            "currency": "USD",
        },
    )
    client: PersonalAIClient = FakePersonalAIClient(candidate)
    result = asyncio.run(client.extract(data))
    with pytest.raises(ValidationError):
        PositionInput.model_validate(result.fields)
    result.fields["quantity"] = "99"
    assert asyncio.run(client.extract(data)).fields["quantity"] == "invented quantity"
    assert "invented quantity" not in repr(candidate)
    assert data.text not in repr(data)


@pytest.mark.parametrize("changed", ["source_id", "schema_id", "schema_version"])
def test_fake_rejects_mismatched_contract_or_source(changed: str) -> None:
    data = request()
    candidate = ExtractionCandidate(
        source_id=data.source_id,
        schema_id=data.schema_id,
        schema_version=data.schema_version,
        fields={},
    )
    other = data.model_copy(
        update={changed: uuid4() if changed == "source_id" else "unsupported"}
    )
    with pytest.raises(PersonalAIError, match="^personal_ai_invalid_response$"):
        asyncio.run(FakePersonalAIClient(candidate).extract(other))


def test_request_bounds_and_envelope_reject_unknown_fields() -> None:
    values = request().model_dump()
    with pytest.raises(ValidationError):
        ExtractionRequest.model_validate({**values, "text": "x" * 100_001})
    with pytest.raises(ValidationError):
        ExtractionRequest.model_validate({**values, "document_path": "/private/file"})
    with pytest.raises(ValidationError):
        ExtractionCandidate.model_validate(
            {
                "source_id": values["source_id"],
                "schema_id": values["schema_id"],
                "schema_version": values["schema_version"],
                "fields": {},
                "write": True,
            }
        )
