"""Exact-body signed user assertions plus independently verified service identity."""

from __future__ import annotations

import base64
import time
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuthPrincipal
from app.integrations.finance_context_auth import FinanceContextIdentityVerifier
from app.integrations.task_wire import VerifiedDelegatedUser, verify_delegated_user


def verify_task_user(request: Request, body: dict[str, Any]) -> VerifiedDelegatedUser:
    settings = request.app.state.settings
    task = settings.task_settings
    if task is None:
        raise HTTPException(404, "not_found")
    auth = request.headers.getlist("authorization")
    assertions = request.headers.getlist("x-user-delegation")
    if len(auth) != 1 or len(assertions) != 1 or not auth[0].startswith("Bearer "):
        raise HTTPException(401, "task_identity_denied")
    try:
        verifier = getattr(
            request.app.state,
            "task_service_verifier",
            FinanceContextIdentityVerifier._google_claims,
        )
        claims = verifier(auth[0][7:], settings.finance_context_service_audience)
        if (
            claims.get("email") != settings.finance_context_service_account
            or claims.get("email_verified") is not True
        ):
            raise ValueError
        key = task.pai_public_key
        identity = verify_delegated_user(
            assertions[0],
            body,
            public_key=Ed25519PublicKey.from_public_bytes(
                base64.b64decode(
                    key + "=" * (-len(key) % 4), altchars=b"-_", validate=True
                )
            ),
            issuer=task.pai_issuer,
            audience=settings.finance_context_service_audience,
            key_id=task.pai_key_id,
            now=int(time.time()),
            allowed_user_issuers=frozenset({"https://accounts.google.com"}),
        )
        if (
            identity.issuer != settings.auth_issuer_url
            or identity.subject != settings.auth_allowed_subject
        ):
            raise ValueError
        return identity
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(401, "task_identity_denied") from error


def active_task_principal(
    session: Session, settings: Any, issuer: str, subject: str
) -> AuthPrincipal:
    principal = session.scalar(
        select(AuthPrincipal).where(
            AuthPrincipal.issuer == issuer,
            AuthPrincipal.subject == subject,
            AuthPrincipal.active.is_(True),
            AuthPrincipal.scope_id == settings.auth_personal_scope_id,
        )
    )
    if principal is None:
        raise HTTPException(401, "task_identity_denied")
    return principal
