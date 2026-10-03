"""OIDC verification, CSRF protection, principal binding, and revocation tests."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from joserfc import jwk, jwt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import service as auth_service
from app.auth.bind_principal import bind_principal
from app.auth.oidc import load_provider_metadata, validate_verified_identity
from app.auth.service import SESSION_COOKIE, get_principal
from app.config import load_settings
from app.db.models import AuthPrincipal, AuthSession, Base, SecurityAuditEvent
from app.db.transactions import run_database_unit as database_retry
from app.main import create_app

ISSUER = "https://identity.example.test"
CLIENT_ID = "finance-synthetic-client"
SUBJECT = "synthetic-personal-subject"
SCOPE_ID = "synthetic-personal-scope"
CALLBACK = "https://finance.example.test/api/v1/auth/callback"


def configure_auth(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_PUBLIC_ORIGIN", "https://finance.example.test")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("PRIVATE_FILE_DIR", str(root / "private"))
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_ISSUER_URL", ISSUER)
    monkeypatch.setenv("AUTH_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "synthetic-confidential-client-secret")
    monkeypatch.setenv(
        "AUTH_SESSION_SIGNING_KEY", "synthetic-session-signing-key-over-32-chars"
    )
    monkeypatch.setenv("AUTH_ALLOWED_SUBJECT", SUBJECT)
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", SCOPE_ID)
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")


def test_principal_binding_is_explicit_and_idempotent() -> None:
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        with session.begin():
            assert (
                bind_principal(
                    session,
                    issuer=ISSUER,
                    subject=SUBJECT,
                    scope_id=SCOPE_ID,
                )
                == "created"
            )
        with session.begin():
            assert (
                bind_principal(
                    session,
                    issuer=ISSUER,
                    subject=SUBJECT,
                    scope_id=SCOPE_ID,
                )
                == "already_bound"
            )
        with pytest.raises(ValueError, match="Refusing to replace"):
            with session.begin():
                bind_principal(
                    session,
                    issuer="https://attacker.example.test",
                    subject=SUBJECT,
                    scope_id="attacker-scope",
                )
    engine.dispose()


def test_slow_session_lookup_does_not_block_health_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_auth(monkeypatch, tmp_path)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    application = create_app(engine=engine)

    def slow_lookup(*_args: Any, **_kwargs: Any) -> None:
        time.sleep(0.2)
        return None

    monkeypatch.setattr("app.main.get_principal", slow_lookup)

    async def requests() -> tuple[float, int]:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://finance.example.test",
        ) as client:
            start = time.monotonic()
            protected = asyncio.create_task(client.get("/v1/accounts"))
            await asyncio.sleep(0)
            health = await client.get("/health")
            elapsed = time.monotonic() - start
            protected_response = await protected
            assert health.status_code == 200
            assert protected_response.status_code == 401
            return elapsed, health.status_code

    elapsed, _ = asyncio.run(requests())
    engine.dispose()
    assert elapsed < 0.15


def test_session_database_retry_reuses_one_token_and_logical_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_auth(monkeypatch, tmp_path)
    settings = load_settings()
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as session, session.begin():
        session.add(
            AuthPrincipal(
                id=uuid4(),
                issuer=ISSUER,
                subject=SUBJECT,
                scope_id=SCOPE_ID,
                active=True,
            )
        )

    token_calls = 0
    original_token = secrets.token_urlsafe

    def token_once(length: int) -> str:
        nonlocal token_calls
        token_calls += 1
        return original_token(length)

    class SyntheticRollback(Exception):
        pass

    def retry_after_rollback(factory_arg: Any, operation: Any) -> Any:
        with factory_arg() as session:
            try:
                with session.begin():
                    operation(session)
                    raise SyntheticRollback
            except SyntheticRollback:
                pass
        return database_retry(factory_arg, operation, sleep=lambda _seconds: None)

    monkeypatch.setattr(secrets, "token_urlsafe", token_once)
    monkeypatch.setattr(auth_service, "run_database_unit", retry_after_rollback)
    created = auth_service.create_session(
        factory,
        settings,
        issuer=ISSUER,
        subject=SUBJECT,
        scope_id=SCOPE_ID,
        correlation_id="synthetic-retry-correlation",
    )
    assert created is not None
    token, context = created
    assert token_calls == 1
    assert context.session_id is not None
    with Session(engine) as session:
        assert session.scalar(select(AuthSession.id)) == context.session_id
        assert len(session.scalars(select(SecurityAuditEvent.id)).all()) == 1
    engine.dispose()


def test_verified_claim_allowlist_checks_issuer_subject_audience_and_expiry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_auth(monkeypatch, tmp_path)
    settings = load_settings()
    claims = {
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": CLIENT_ID,
        "exp": 2_000_000_000,
    }
    assert (
        validate_verified_identity(claims, settings, now=1_900_000_000).subject
        == SUBJECT
    )
    for invalid in (
        {**claims, "iss": "https://attacker.example.test"},
        {**claims, "sub": "attacker-subject"},
        {**claims, "aud": "other-client"},
        {**claims, "exp": 1_800_000_000},
        {**claims, "aud": [CLIENT_ID, "other-client"]},
        {**claims, "aud": CLIENT_ID, "azp": "other-client"},
    ):
        with pytest.raises(ValueError):
            validate_verified_identity(invalid, settings, now=1_900_000_000)


def test_discovery_requires_configured_issuer_and_https_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    configure_auth(monkeypatch, tmp_path)
    settings = load_settings()
    good = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
    }

    def load(metadata: dict[str, str]) -> Mapping[str, Any]:
        client = SimpleNamespace(load_server_metadata=_constant_async(metadata))
        return asyncio.run(load_provider_metadata(client, settings))

    assert load(good) == good
    for invalid in (
        {**good, "issuer": "https://attacker.example.test"},
        {**good, "token_endpoint": "http://identity.example.test/token"},
        {**good, "jwks_uri": "https://user:pass@identity.example.test/jwks"},
    ):
        with pytest.raises(ValueError):
            load(invalid)


def test_oidc_callback_verifies_jwt_binds_server_scope_and_revokes_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_auth(monkeypatch, tmp_path)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    principal_id = uuid4()
    with Session(engine) as session:
        session.add(
            AuthPrincipal(
                id=principal_id,
                issuer=ISSUER,
                subject=SUBJECT,
                scope_id=SCOPE_ID,
                active=True,
            )
        )
        session.commit()

    app = create_app(engine=engine)
    oidc_client = app.state.oidc_client
    signing_key = jwk.generate_key("RSA", 2048, private=True, auto_kid=True)
    public_key = signing_key.as_dict(private=False)
    metadata = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    oidc_client.load_server_metadata = _constant_async(metadata)
    oidc_client.fetch_jwk_set = _constant_async({"keys": [public_key]})
    token_claims: dict[str, object] = {}

    async def fetch_access_token(**_kwargs: object) -> dict[str, str]:
        encoded = jwt.encode(
            {"alg": "RS256", "kid": public_key["kid"]},
            token_claims,
            signing_key,
        )
        return {"id_token": encoded}

    oidc_client.fetch_access_token = fetch_access_token
    client = TestClient(app, base_url="https://finance.example.test")

    def begin_login() -> tuple[str, str]:
        login = client.get("/v1/auth/login", follow_redirects=False)
        assert login.status_code == 302
        cookie_header = login.headers["set-cookie"].casefold()
        assert "pf_oidc_transaction" in cookie_header
        assert "httponly" in cookie_header
        assert "secure" in cookie_header
        assert "samesite=lax" in cookie_header
        authorize_url = urlparse(login.headers["location"])
        parameters = parse_qs(authorize_url.query)
        assert authorize_url.netloc == "identity.example.test"
        assert parameters["redirect_uri"] == [CALLBACK]
        assert parameters["code_challenge_method"] == ["S256"]
        return parameters["state"][0], parameters["nonce"][0]

    def callback(state: str) -> Any:
        return client.get(
            "/v1/auth/callback",
            params={"code": "synthetic-code", "state": state},
            follow_redirects=False,
        )

    state, nonce = begin_login()
    token_claims.update(
        {
            "iss": ISSUER,
            "sub": SUBJECT,
            "aud": CLIENT_ID,
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "nonce": nonce,
        }
    )
    success = callback(state)
    assert success.status_code == 303
    assert success.headers["location"] == "https://finance.example.test"
    assert "httponly" in success.headers["set-cookie"].casefold()
    assert "secure" in success.headers["set-cookie"].casefold()
    assert client.get("/v1/accounts").status_code == 200

    with Session(engine) as session:
        stored = session.scalar(select(AuthSession))
        assert stored is not None
        browser_cookie = client.cookies.get(SESSION_COOKIE)
        assert browser_cookie is not None
        assert stored.token_hash != browser_cookie
        assert len(stored.token_hash) == 64
        principal = session.get(AuthPrincipal, principal_id)
        assert principal is not None
        assert principal.scope_id == SCOPE_ID
        assert principal.issuer == ISSUER
    assert (
        get_principal(app.state.session_factory, app.state.settings, browser_cookie)
        is not None
    )
    assert (
        get_principal(
            app.state.session_factory,
            replace(app.state.settings, auth_allowed_subject="another-subject"),
            browser_cookie,
        )
        is None
    )

    assert (
        client.post(
            "/v1/accounts",
            headers={
                "Origin": "https://finance.example.test",
                "Sec-Fetch-Site": "cross-site",
            },
            json={"name": "Denied", "account_type": "taxable", "base_currency": "USD"},
        ).status_code
        == 403
    )
    logout = client.post(
        "/v1/auth/logout", headers={"Origin": "https://finance.example.test"}
    )
    assert logout.status_code == 204
    assert client.get("/v1/accounts").status_code == 401
    with Session(engine) as session:
        stored = session.scalar(select(AuthSession))
        assert stored is not None and stored.revoked_at is not None
        audit = list(session.scalars(select(SecurityAuditEvent)))
        assert {event.action for event in audit} == {"auth.login", "auth.logout"}
        assert all(event.correlation_id for event in audit)

    engine.dispose()


def test_oidc_rejects_bad_signature_and_wrong_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_auth(monkeypatch, tmp_path)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            AuthPrincipal(
                id=uuid4(),
                issuer=ISSUER,
                subject=SUBJECT,
                scope_id=SCOPE_ID,
                active=True,
            )
        )
        session.commit()
    app = create_app(engine=engine)
    client = TestClient(app, base_url="https://finance.example.test")
    oidc_client = app.state.oidc_client
    signing_key = jwk.generate_key("RSA", 2048, private=True, auto_kid=True)
    wrong_key = jwk.generate_key("RSA", 2048, private=True, auto_kid=True)
    public_key = signing_key.as_dict(private=False)
    oidc_client.load_server_metadata = _constant_async(
        {
            "issuer": ISSUER,
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "jwks_uri": f"{ISSUER}/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
    )
    oidc_client.fetch_jwk_set = _constant_async({"keys": [public_key]})
    signing_key_for_test: Any = wrong_key
    nonce_for_test = ""

    async def make_identity_token(**_kwargs: object) -> dict[str, str]:
        signed = jwt.encode(
            {"alg": "RS256", "kid": public_key["kid"]},
            {
                "iss": ISSUER,
                "sub": "attacker-subject",
                "aud": CLIENT_ID,
                "exp": int(time.time()) + 3600,
                "iat": int(time.time()),
                "nonce": nonce_for_test,
            },
            signing_key_for_test,
        )
        return {"id_token": signed}

    oidc_client.fetch_access_token = make_identity_token
    state, nonce_for_test = parse_authorization(client)
    bad_signature = client.get(
        "/v1/auth/callback",
        params={"code": "synthetic", "state": state},
    )
    assert bad_signature.status_code == 401
    assert client.get("/v1/accounts").status_code == 401

    signing_key_for_test = signing_key
    state, nonce_for_test = parse_authorization(client)
    denied = client.get(
        "/v1/auth/callback", params={"code": "synthetic", "state": state}
    )
    assert denied.status_code == 401
    assert client.get("/v1/accounts").status_code == 401
    engine.dispose()


def _constant_async(value: Any) -> Callable[..., Awaitable[Any]]:
    async def result(*_args: object, **_kwargs: object) -> Any:
        return value

    return result


def parse_authorization(client: TestClient) -> tuple[str, str]:
    response = client.get("/v1/auth/login", follow_redirects=False)
    values = parse_qs(urlparse(response.headers["location"]).query)
    return values["state"][0], values["nonce"][0]
