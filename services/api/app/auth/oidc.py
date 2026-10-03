"""Provider-neutral OIDC authorization-code flow and verified identity checks."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]

from app.config import Settings

OIDC_TRANSACTION_COOKIE = "pf_oidc_transaction"
OIDC_CALLBACK_PATH = "/api/v1/auth/callback"


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str


def create_oidc_client(settings: Settings) -> Any | None:
    if not settings.auth_enabled:
        return None
    if (
        settings.auth_issuer_url is None
        or settings.auth_client_id is None
        or settings.auth_client_secret is None
    ):
        raise ValueError("OIDC client configuration is incomplete")
    # Authlib's PKCE helper logs the verifier at DEBUG; suppress that secret
    # even when an operator enables verbose logging for other application code.
    logging.getLogger("authlib.integrations.base_client.sync_app").setLevel(
        logging.INFO
    )
    oauth = OAuth()
    return oauth.register(
        name="finance",
        client_id=settings.auth_client_id,
        client_secret=settings.auth_client_secret,
        server_metadata_url=(
            f"{settings.auth_issuer_url.rstrip('/')}/.well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid",
            "code_challenge_method": "S256",
            "timeout": 10,
        },
    )


def validate_verified_identity(
    claims: Mapping[str, Any], settings: Settings, *, now: float | None = None
) -> VerifiedIdentity:
    """Apply the app allowlist to claims already signature-checked by Authlib."""
    expected_issuer = settings.auth_issuer_url
    expected_audience = settings.auth_client_id
    expected_subject = settings.auth_allowed_subject
    if expected_issuer is None or expected_audience is None or expected_subject is None:
        raise ValueError("OIDC allowlist configuration is incomplete")

    issuer = claims.get("iss")
    subject = claims.get("sub")
    expiration = claims.get("exp")
    audience = claims.get("aud")
    authorized_party = claims.get("azp")
    if issuer != expected_issuer:
        raise ValueError("Identity issuer is not allowed")
    if not isinstance(subject, str) or subject != expected_subject:
        raise ValueError("Identity subject is not allowed")
    if not isinstance(expiration, (int, float)) or isinstance(expiration, bool):
        raise ValueError("Identity token has no valid expiration")
    if expiration <= (time.time() if now is None else now):
        raise ValueError("Identity token is expired")
    audiences = [audience] if isinstance(audience, str) else audience
    if (
        not isinstance(audiences, list)
        or not audiences
        or not all(isinstance(value, str) for value in audiences)
        or expected_audience not in audiences
    ):
        raise ValueError("Identity audience is not allowed")
    if authorized_party is not None and authorized_party != expected_audience:
        raise ValueError("Identity authorized party is not allowed")
    if len(audiences) > 1 and authorized_party != expected_audience:
        raise ValueError("Multiple identity audiences require the allowed party")
    return VerifiedIdentity(expected_issuer, subject)


async def load_provider_metadata(client: Any, settings: Settings) -> Mapping[str, Any]:
    """Require issuer-matched discovery and HTTPS endpoints before client use."""
    raw_metadata = await client.load_server_metadata()
    if not isinstance(raw_metadata, Mapping):
        raise ValueError("Identity provider discovery response is invalid")
    metadata = cast(Mapping[str, Any], raw_metadata)
    expected_issuer = settings.auth_issuer_url
    if expected_issuer is None or metadata.get("issuer") != expected_issuer:
        raise ValueError("Identity provider issuer metadata does not match config")
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        endpoint = metadata.get(name)
        if not isinstance(endpoint, str):
            raise ValueError(f"Identity provider metadata has no {name}")
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError(f"Identity provider {name} must use HTTPS")
    return metadata
