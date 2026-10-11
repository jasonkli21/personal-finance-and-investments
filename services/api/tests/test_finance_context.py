"""Read-only, owner-bound Finance projection for Personal AI."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.finance_context_routes import MAX_REQUEST_BYTES
from app.config import Settings, load_settings
from app.db.models import (
    Account,
    AccountBalanceObservation,
    AuthPrincipal,
    Base,
    Issuer,
    PositionSnapshot,
    PositionSnapshotLine,
    ReportedFact,
    ResearchDocument,
    ResearchThesisNote,
    Security,
)
from app.domains.finance_context import (
    read_finance_context,
)
from app.integrations.finance_context import (
    FinanceContextEntityReference,
    FinanceContextReadRequest,
)
from app.integrations.finance_context_auth import (
    FinanceContextAuthorizationError,
    FinanceContextIdentityVerifier,
    VerifiedFinanceContextIdentity,
)
from app.main import create_app


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _account(session: Session, *, account_id: UUID | None = None) -> Account:
    account = Account(
        id=account_id or uuid4(),
        name="Brokerage",
        account_type="brokerage",
        base_currency="USD",
        active=True,
        current_position_revision=4,
        source_type="manual",
    )
    session.add(account)
    session.flush()
    session.add(
        AccountBalanceObservation(
            id=uuid4(),
            account_id=account.id,
            as_of=date(2026, 10, 10),
            revision=1,
            balance_kind="total",
            amount=Decimal("1250.50"),
            currency="USD",
            source="manual_entry",
            quality_status="reported",
            idempotency_key=f"balance:{account.id}",
        )
    )
    session.flush()
    return account


def _request(
    *,
    refs: tuple[FinanceContextEntityReference, ...],
    fields: tuple[str, ...],
    include_broader_context: bool = False,
    max_results: int = 8,
) -> FinanceContextReadRequest:
    return FinanceContextReadRequest(
        operation="current",
        entity_refs=refs,
        fields=fields,
        include_broader_context=include_broader_context,
        max_results=max_results,
        max_bytes=16_384,
    )


def test_finance_read_contract_is_bounded_and_forbids_body_supplied_owner() -> None:
    account_id = str(uuid4())
    valid = _request(
        refs=(
            FinanceContextEntityReference(entity_type="account", entity_id=account_id),
        ),
        fields=("account_summary",),
    )
    assert valid.max_results <= 32
    assert valid.max_bytes <= 32_768
    assert "owner_id" not in valid.model_dump(mode="json")
    assert MAX_REQUEST_BYTES == 8_192

    with pytest.raises(ValidationError):
        FinanceContextReadRequest.model_validate(
            {
                **valid.model_dump(mode="json"),
                "owner_id": "attacker-selected-owner",
            }
        )
    with pytest.raises(ValidationError):
        _request(
            refs=(
                FinanceContextEntityReference(
                    entity_type="portfolio", entity_id="all_active"
                ),
            ),
            fields=("position_summary",),
        )


def test_account_projection_preserves_provenance_and_permission_version(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session:
        account = _account(session)
        session.commit()
        request = _request(
            refs=(
                FinanceContextEntityReference(
                    entity_type="account", entity_id=str(account.id)
                ),
            ),
            fields=("account_summary", "balance_summary"),
        )

        response = read_finance_context(
            session, request, principal_scope_id="personal-scope"
        )

        assert len(response.items) == 1
        record = response.items[0]
        assert record.entity_type == "account"
        assert record.source_class == "domain_current"
        assert record.authority == "authoritative"
        assert record.sensitivity == "restricted"
        assert record.source_version == record.permission_dependencies[0].version
        assert len(record.source_version) == 64
        amount = record.payload["balance_summary"]["amount"]
        assert amount.value == "1250.5000000000"
        assert amount.semantic_class == "observed"
        assert amount.state == "known"
        assert amount.unit == "currency_amount"
        assert amount.currency == "USD"
        assert amount.as_of == "2026-10-10"
        assert amount.evidence_refs
        assert not {"raw_value", "source_url", "private_path"} & set(record.payload)

        verify = FinanceContextReadRequest(
            operation="verify",
            entity_refs=request.entity_refs,
            fields=("permission_version",),
            max_results=1,
            max_bytes=4096,
        )
        verified = read_finance_context(
            session, verify, principal_scope_id="personal-scope"
        )
        assert (
            verified.items[0].source_version
            == record.permission_dependencies[0].version
        )


def test_missing_balance_is_preserved_as_unknown_not_zero(
    sqlite_engine: Engine,
) -> None:
    account_id = uuid4()
    with Session(sqlite_engine) as session:
        session.add(
            Account(
                id=account_id,
                name="Account without balance observation",
                account_type="brokerage",
                base_currency="USD",
                active=True,
                current_position_revision=0,
                source_type="manual",
            )
        )
        session.commit()
        response = read_finance_context(
            session,
            _request(
                refs=(
                    FinanceContextEntityReference(
                        entity_type="account", entity_id=str(account_id)
                    ),
                ),
                fields=("balance_summary",),
            ),
            principal_scope_id="personal-scope",
        )

    amount = response.items[0].payload["balance_summary"]["amount"]
    assert amount.value is None
    assert amount.state == "unknown"
    assert amount.authority == "unknown"
    assert amount.currency == "USD"
    assert amount.uncertainty


def test_broader_positions_use_only_current_accepted_snapshot(
    sqlite_engine: Engine,
) -> None:
    with Session(sqlite_engine) as session:
        account = _account(session)
        current_security = Security(
            id=uuid4(),
            security_type="equity",
            display_ticker="CUR",
            name="Current Holding",
            currency="USD",
        )
        historic_security = Security(
            id=uuid4(),
            security_type="equity",
            display_ticker="OLD",
            name="Historic Holding",
            currency="USD",
        )
        session.add_all((current_security, historic_security))
        session.flush()
        current = PositionSnapshot(
            id=uuid4(),
            account_id=account.id,
            snapshot_at=datetime(2026, 10, 10, tzinfo=UTC),
            source="manual",
            status="accepted",
            revision=4,
        )
        historic = PositionSnapshot(
            id=uuid4(),
            account_id=account.id,
            snapshot_at=datetime(2026, 9, 10, tzinfo=UTC),
            source="manual",
            status="accepted",
            revision=3,
        )
        session.add_all((current, historic))
        session.flush()
        session.add_all(
            (
                PositionSnapshotLine(
                    id=uuid4(),
                    snapshot_id=current.id,
                    security_id=current_security.id,
                    quantity=Decimal("2"),
                    reported_value=Decimal("100"),
                    reported_price=Decimal("50"),
                    currency="USD",
                    source="manual",
                    quality_status="reported",
                ),
                PositionSnapshotLine(
                    id=uuid4(),
                    snapshot_id=historic.id,
                    security_id=historic_security.id,
                    quantity=Decimal("9"),
                    reported_value=Decimal("900"),
                    reported_price=Decimal("100"),
                    currency="USD",
                    source="manual",
                    quality_status="reported",
                ),
            )
        )
        account.current_position_snapshot_id = current.id
        session.flush()
        session.commit()

        request = _request(
            refs=(
                FinanceContextEntityReference(
                    entity_type="portfolio", entity_id="all_active"
                ),
            ),
            fields=("position_summary",),
            include_broader_context=True,
        )
        response = read_finance_context(
            session, request, principal_scope_id="personal-scope"
        )

        assert len(response.items) == 1
        position = response.items[0]
        assert position.entity_type == "position"
        assert position.payload["position_summary"]["security"].value == "CUR"
        assert all(
            ref.kind == "record" and len(ref.fingerprint) == 64
            for ref in position.source_refs
        )
        original_version = position.permission_dependencies[0].version
        line = session.get(PositionSnapshotLine, UUID(position.entity_id))
        assert line is not None
        line.quantity = Decimal("3")
        session.flush()
        verify = FinanceContextReadRequest(
            operation="verify",
            entity_refs=(
                FinanceContextEntityReference(
                    entity_type="position", entity_id=position.entity_id
                ),
            ),
            fields=("permission_version",),
            max_results=1,
            max_bytes=4096,
        )
        verified = read_finance_context(
            session, verify, principal_scope_id="personal-scope"
        )
        assert verified.items[0].source_version != original_version


def test_thesis_and_external_research_facts_keep_distinct_authority_and_provenance(
    sqlite_engine: Engine,
) -> None:
    issuer_id = uuid4()
    thesis_id = uuid4()
    document_id = uuid4()
    fact_id = uuid4()
    conflict_fact_id = uuid4()
    with Session(sqlite_engine) as session:
        session.add(
            Issuer(
                id=issuer_id,
                normalized_name="example-inc",
                display_name="Example Inc.",
            )
        )
        session.add(
            ResearchThesisNote(
                id=thesis_id,
                issuer_id=issuer_id,
                version=2,
                text="User-authored thesis",
                idempotency_key="thesis-v2",
            )
        )
        session.add(
            ResearchDocument(
                id=document_id,
                issuer_id=issuer_id,
                cik="0000000001",
                accession_number="0000000001-26-000001",
                form_type="10-K",
                title="Registered filing",
                source_url="https://example.test/private-filing",
                filing_date=date(2026, 10, 1),
                period_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
                source_status="user_supplied_unverified",
            )
        )
        session.add(
            ReportedFact(
                id=fact_id,
                document_id=document_id,
                taxonomy="us-gaap",
                concept="Revenue",
                raw_value="123.45 (raw source value)",
                normalized_value=Decimal("123.45"),
                unit="USD",
                currency="USD",
                period_kind="duration",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
                quality_status="user_supplied_unverified",
                idempotency_key="fact-v1",
            )
        )
        session.add(
            ReportedFact(
                id=conflict_fact_id,
                document_id=document_id,
                taxonomy="us-gaap",
                concept="Revenue",
                raw_value="conflicting source value",
                normalized_value=Decimal("321.00"),
                unit="USD",
                currency="USD",
                period_kind="duration",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
                quality_status="conflict",
                idempotency_key="fact-conflict-v1",
            )
        )
        session.commit()

        thesis = read_finance_context(
            session,
            _request(
                refs=(
                    FinanceContextEntityReference(
                        entity_type="issuer", entity_id=str(issuer_id)
                    ),
                ),
                fields=("research_thesis",),
            ),
            principal_scope_id="personal-scope",
        ).items[0]
        fact = read_finance_context(
            session,
            _request(
                refs=(
                    FinanceContextEntityReference(
                        entity_type="research_fact", entity_id=str(fact_id)
                    ),
                ),
                fields=("research_fact",),
            ),
            principal_scope_id="personal-scope",
        ).items[0]
        conflict = read_finance_context(
            session,
            _request(
                refs=(
                    FinanceContextEntityReference(
                        entity_type="research_fact",
                        entity_id=str(conflict_fact_id),
                    ),
                ),
                fields=("research_fact",),
            ),
            principal_scope_id="personal-scope",
        ).items[0]

    assert thesis.source_class == "domain_current"
    assert thesis.authority == "user_asserted"
    assert thesis.payload["research_thesis"]["text"].value == "User-authored thesis"
    assert thesis.source_refs[0].kind == "record"
    assert fact.source_class == "external_research"
    assert fact.authority == "user_asserted"
    assert fact.payload["research_fact"]["value"].semantic_class == "observed"
    assert fact.payload["research_fact"]["value"].state == "known"
    uncertainty = fact.payload["research_fact"]["value"].uncertainty
    assert uncertainty is not None
    assert "unverified" in uncertainty
    assert fact.payload["research_fact"]["value"].currency == "USD"
    assert all(reference.kind == "evidence" for reference in fact.source_refs)
    assert conflict.payload["research_fact"]["value"].state == "conflict"
    serialized = thesis.model_dump_json() + fact.model_dump_json()
    assert "private-filing" not in serialized
    assert "raw source value" not in serialized


def test_read_route_is_absent_from_default_openapi_and_returns_404(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine: Engine
) -> None:
    monkeypatch.delenv("FINANCE_CONTEXT_READ_ENABLED", raising=False)
    app = create_app(engine=sqlite_engine)
    path = "/v1/integrations/personal-ai/context"
    with TestClient(app) as client:
        assert path not in client.get("/openapi.json").json()["paths"]
        response = client.post(path, json={})
        assert response.status_code == 404
    assert app.state.personal_ai_client.__class__.__name__ == "DisabledPersonalAIClient"


def test_read_route_uses_dual_identity_and_principal_binding(
    monkeypatch: pytest.MonkeyPatch, sqlite_engine: Engine
) -> None:
    settings = {
        "APP_ENV": "development",
        "APP_PUBLIC_ORIGIN": "https://finance.example.test",
        "AUTH_ENABLED": "true",
        "AUTH_ISSUER_URL": "https://accounts.google.com",
        "AUTH_CLIENT_ID": "finance-client",
        "AUTH_CLIENT_SECRET": "synthetic-secret",
        "AUTH_SESSION_SIGNING_KEY": "a" * 48,
        "AUTH_ALLOWED_SUBJECT": "google-subject",
        "AUTH_PERSONAL_SCOPE_ID": "personal-scope",
        "AUTH_COOKIE_SECURE": "true",
        "JOB_WORKER_ENABLED": "false",
        "FINANCE_CONTEXT_READ_ENABLED": "true",
        "FINANCE_CONTEXT_SERVICE_AUDIENCE": "https://finance.example.test",
        "FINANCE_CONTEXT_SERVICE_ACCOUNT": (
            "personal-ai@project.iam.gserviceaccount.com"
        ),
        "FINANCE_CONTEXT_USER_AUDIENCE": "finance-user-client",
        "PRIVATE_FILE_DIR": "/tmp/finance-context-test",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    with Session(sqlite_engine) as session:
        account = _account(session)
        account_id = str(account.id)
        session.add(
            AuthPrincipal(
                id=uuid4(),
                issuer="https://accounts.google.com",
                subject="google-subject",
                scope_id="personal-scope",
                active=True,
            )
        )
        session.commit()

    class FakeVerifier:
        subject = "google-subject"

        def verify(
            self,
            *,
            service_token: str,
            user_token: str,
            settings: Settings,
        ) -> VerifiedFinanceContextIdentity:
            assert service_token == "service-token"
            assert user_token == "user-token"
            assert settings.finance_context_read_enabled is True
            return VerifiedFinanceContextIdentity(
                issuer="https://accounts.google.com",
                subject=self.subject,
            )

    app = create_app(engine=sqlite_engine)
    verifier = FakeVerifier()
    app.state.finance_context_identity_verifier = verifier
    payload = {
        "operation": "current",
        "entity_refs": [{"entity_type": "account", "entity_id": account_id}],
        "fields": ["account_summary", "balance_summary"],
        "max_results": 2,
        "max_bytes": 8192,
    }
    path = "/v1/integrations/personal-ai/context"
    before = None
    with Session(sqlite_engine) as session:
        before = session.scalar(
            select(func.count()).select_from(AccountBalanceObservation)
        )
    with TestClient(app) as client:
        assert path in client.get("/openapi.json").json()["paths"]
        response = client.post(
            path,
            json=payload,
            headers={
                "Authorization": "Bearer service-token",
                "X-User-ID-Token": "user-token",
            },
        )
        oversized = client.post(
            path,
            content=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={
                "Authorization": "Bearer service-token",
                "X-User-ID-Token": "user-token",
                "Content-Type": "application/json",
            },
        )
        verifier.subject = "different-google-subject"
        wrong_principal = client.post(
            path,
            json=payload,
            headers={
                "Authorization": "Bearer service-token",
                "X-User-ID-Token": "user-token",
            },
        )
        with Session(sqlite_engine) as session:
            after = session.scalar(
                select(func.count()).select_from(AccountBalanceObservation)
            )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    amount = response.json()["items"][0]["payload"]["balance_summary"]["amount"]
    assert amount["value"] == "1250.5000000000"
    assert amount["currency"] == "USD"
    assert response.json()["items"][0]["source_class"] == "domain_current"
    assert "source_url" not in response.text
    assert oversized.status_code == 413
    assert wrong_principal.status_code == 401
    assert before == after


def test_oidc_verifier_checks_distinct_audiences_and_pinned_user_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC).timestamp()
    settings = cast(
        Settings,
        SimpleNamespace(
            finance_context_read_enabled=True,
            finance_context_service_audience="service-audience",
            finance_context_service_account="personal-ai@project.iam.gserviceaccount.com",
            finance_context_user_audience="user-audience",
            finance_context_user_token_max_age_seconds=300,
            auth_allowed_subject="google-subject",
            auth_issuer_url="https://accounts.google.com",
        ),
    )
    calls: list[tuple[str, str]] = []
    claims: dict[str, dict[str, Any]] = {
        "service": {
            "email": settings.finance_context_service_account,
            "email_verified": True,
        },
        "user": {
            "iss": "https://accounts.google.com",
            "sub": "google-subject",
            "iat": now,
        },
    }

    def verify_claims(token: str, audience: str) -> dict[str, Any]:
        calls.append((token, audience))
        return claims[token]

    monkeypatch.setattr(
        FinanceContextIdentityVerifier,
        "_google_claims",
        staticmethod(verify_claims),
    )
    identity = FinanceContextIdentityVerifier().verify(
        service_token="service",
        user_token="user",
        settings=settings,
    )
    assert identity == VerifiedFinanceContextIdentity(
        issuer="https://accounts.google.com", subject="google-subject"
    )
    assert calls == [
        ("service", "service-audience"),
        ("user", "user-audience"),
    ]

    claims["user"]["sub"] = "other-subject"
    with pytest.raises(FinanceContextAuthorizationError):
        FinanceContextIdentityVerifier().verify(
            service_token="service",
            user_token="user",
            settings=settings,
        )


def test_finance_read_gate_defaults_off_and_rejects_unbound_enablement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FINANCE_CONTEXT_READ_ENABLED", raising=False)
    assert load_settings().finance_context_read_enabled is False
    monkeypatch.setenv("FINANCE_CONTEXT_READ_ENABLED", "true")
    with pytest.raises(
        ValueError, match="finance_context_identity_configuration_required"
    ):
        load_settings()
