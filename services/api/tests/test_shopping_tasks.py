"""Finance-owned immutable commands, consent/revision, signed identity and relay."""

from __future__ import annotations

import base64
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.bind_principal import bind_principal
from app.auth.service import SESSION_COOKIE, create_session
from app.db.models import Base, DelegatedSourceCommand
from app.integrations.task_wire import (
    COMMAND_READ_FINGERPRINT,
    DelegatedCommandRead,
    sign_delegated_user,
)
from app.main import create_app


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def task_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, engine: Engine | None = None
) -> Iterator[tuple[TestClient, Ed25519PrivateKey]]:
    source, pai = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    values = {
        "APP_ENV": "test",
        "APP_PUBLIC_ORIGIN": "https://testserver",
        "JOB_WORKER_ENABLED": "false",
        "AUTH_ENABLED": "true",
        "AUTH_ISSUER_URL": "https://accounts.google.com",
        "AUTH_CLIENT_ID": "test-client",
        "AUTH_CLIENT_SECRET": "synthetic-secret",
        "AUTH_SESSION_SIGNING_KEY": "synthetic-session-key-that-is-at-least-32-bytes",
        "AUTH_ALLOWED_SUBJECT": "synthetic-user",
        "AUTH_PERSONAL_SCOPE_ID": "synthetic-scope",
        "AUTH_COOKIE_SECURE": "false",
        "PRIVATE_FILE_DIR": str(tmp_path / "private"),
        "FINANCE_CONTEXT_READ_ENABLED": "true",
        "FINANCE_CONTEXT_SERVICE_AUDIENCE": "https://finance.example.invalid",
        "FINANCE_CONTEXT_SERVICE_ACCOUNT": (
            "pai@synthetic-project.iam.gserviceaccount.com"
        ),
        "FINANCE_CONTEXT_USER_AUDIENCE": "test-client",
        "FINANCE_TASKS_ENABLED": "true",
        "PERSONAL_AI_TASK_BASE_URL": "https://pai.example.invalid",
        "PERSONAL_AI_TASK_AUDIENCE": "https://pai.example.invalid",
        "FINANCE_TASK_SERVICE_ACCOUNT": (
            "finance@synthetic-project.iam.gserviceaccount.com"
        ),
        "FINANCE_TASK_ISSUER": "finance-test",
        "FINANCE_TASK_KEY_ID": "finance-key",
        "FINANCE_TASK_PRIVATE_KEY": encode(
            source.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        ),
        "PERSONAL_AI_TASK_ISSUER": "pai-test",
        "PERSONAL_AI_TASK_KEY_ID": "pai-key",
        "PERSONAL_AI_TASK_PUBLIC_KEY": encode(
            pai.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ),
        "FINANCE_TASK_SHOPPING_OPERATION_FINGERPRINT": "f" * 64,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    engine = engine or create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = create_app(engine=engine)
    with Session(engine) as session, session.begin():
        bind_principal(
            session,
            issuer="https://accounts.google.com",
            subject="synthetic-user",
            scope_id="synthetic-scope",
        )
    created = create_session(
        app.state.session_factory,
        app.state.settings,
        issuer="https://accounts.google.com",
        subject="synthetic-user",
        scope_id="synthetic-scope",
        correlation_id="synthetic-login",
        authenticated_at=int(time.time()),
    )
    assert created is not None
    app.state.task_service_verifier = lambda token, audience: {
        "email": "pai@synthetic-project.iam.gserviceaccount.com",
        "email_verified": True,
    }
    with TestClient(app, base_url="https://testserver") as client:
        client.cookies.set(SESSION_COOKIE, created[0])
        response = client.put(
            "/v1/finance/discretionary-budgets/2026-10",
            headers={"Origin": "https://testserver"},
            json={
                "expected_revision": 0,
                "amount": "50.00",
                "currency": "USD",
                "share_with_shopping": True,
            },
        )
        assert response.status_code == 200, response.text
        yield client, pai


def choice() -> dict[str, Any]:
    return {
        "command_id": str(uuid4()),
        "period": "2026-10",
        "expected_budget_revision": 1,
        "context_choice_id": "a" * 43,
        "shopping_project_id": str(uuid4()),
        "expected_project_revision": 1,
    }


def create(client: TestClient, body: dict[str, Any]) -> Response:
    return client.post(
        "/v1/finance/shopping-tasks/commands",
        json=body,
        headers={"Origin": "https://testserver"},
    )


def signed_read(
    client: TestClient,
    key: Ed25519PrivateKey,
    command_id: str,
    *,
    changed_body: bool = False,
) -> Response:
    body = DelegatedCommandRead(
        destination_application_id="finance", command_id=UUID(command_id)
    ).model_dump(mode="json")
    assertion = sign_delegated_user(
        user_issuer="https://accounts.google.com",
        user_subject="synthetic-user",
        authenticated_at=int(time.time()),
        private_key=key,
        issuer="pai-test",
        audience="https://finance.example.invalid",
        key_id="pai-key",
        request_body=body,
    )
    if changed_body:
        body["command_id"] = str(uuid4())
    return client.post(
        "/internal/personal-ai/commands/read",
        json=body,
        headers={
            "Authorization": "Bearer synthetic-service",
            "X-User-Delegation": assertion,
            "X-Task-Contract-Fingerprint": COMMAND_READ_FINGERPRINT,
        },
    )


def test_command_replay_retains_original_bytes_and_rejects_changed_choice(
    task_host: tuple[TestClient, Ed25519PrivateKey],
) -> None:
    client, key = task_host
    body = choice()
    first = create(client, body)
    assert first.status_code == 201, first.text
    assert create(client, body).json() == first.json()
    assert first.json()["payload"] == {"amount": "50.00", "currency": "USD"}
    assert signed_read(client, key, body["command_id"]).json() == first.json()
    assert (
        create(client, body | {"shopping_project_id": str(uuid4())}).status_code == 409
    )
    with cast(FastAPI, client.app).state.session_factory() as session:
        rows = list(session.query(DelegatedSourceCommand))
        assert len(rows) == 1 and rows[0].proposal_id is None
        assert "token" not in str(rows[0].command).lower()


def test_signed_read_checks_current_consent_revision_and_exact_request(
    task_host: tuple[TestClient, Ed25519PrivateKey],
) -> None:
    client, key = task_host
    body = choice()
    assert create(client, body).status_code == 201
    assert (
        signed_read(client, key, body["command_id"], changed_body=True).status_code
        == 401
    )
    response = client.put(
        "/v1/finance/discretionary-budgets/2026-10",
        headers={"Origin": "https://testserver"},
        json={
            "expected_revision": 1,
            "amount": "50.00",
            "currency": "USD",
            "share_with_shopping": False,
        },
    )
    assert response.status_code == 200
    assert signed_read(client, key, body["command_id"]).status_code == 409
    assert create(client, choice()).status_code == 409


def test_new_command_requires_current_verified_authentication_and_origin(
    task_host: tuple[TestClient, Ed25519PrivateKey],
) -> None:
    client, _ = task_host
    assert (
        client.post("/v1/finance/shopping-tasks/commands", json=choice()).status_code
        == 403
    )
    from app.db.models import AuthSession

    with cast(FastAPI, client.app).state.session_factory() as session, session.begin():
        row = session.query(AuthSession).one()
        row.upstream_auth_time = int(time.time()) - 301
    assert create(client, choice()).status_code == 401
    assert client.get("/v1/finance/shopping-tasks/capabilities").json() == {
        "enabled": True,
        "recent_authentication": False,
    }


def test_budget_verification_and_current_share_canonical_identity(
    task_host: tuple[TestClient, Ed25519PrivateKey],
) -> None:
    from app.db.models import MonthlyDiscretionaryBudget
    from app.domains.finance_context import read_finance_context
    from app.integrations.finance_context import (
        FinanceContextEntityReference,
        FinanceContextReadRequest,
        FinanceContextRecord,
    )

    client, _ = task_host
    with cast(FastAPI, client.app).state.session_factory() as session:
        budget = session.query(MonthlyDiscretionaryBudget).one()
        ref = FinanceContextEntityReference(
            entity_type="discretionary_budget", entity_id=str(budget.id)
        )

        def read(
            operation: Literal["current", "verify"], fields: tuple[str, ...]
        ) -> FinanceContextRecord:
            return read_finance_context(
                session,
                FinanceContextReadRequest(
                    operation=operation,
                    purpose="shopping_discretionary_budget",
                    destination_application_id="shopping",
                    entity_refs=(ref,),
                    fields=fields,
                    max_results=1,
                    max_bytes=4096,
                ),
                principal_scope_id="synthetic-scope",
            ).items[0]

        current = read("current", ("amount", "currency", "period"))
        verified = read("verify", ("permission_version",))
        assert (
            current.source_id
            == verified.source_id
            == f"finance:monthly_discretionary_budget:{budget.id}"
        )
        assert current.source_refs == verified.source_refs
        assert current.source_version == verified.source_version
        assert current.permission_dependencies == verified.permission_dependencies
