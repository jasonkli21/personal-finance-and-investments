"""Database-backed, revocable browser sessions for the single personal scope."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import AuthPrincipal, AuthSession, SecurityAuditEvent, utc_now
from app.db.transactions import run_database_unit

SESSION_COOKIE = "pf_session"


@dataclass(frozen=True)
class PrincipalContext:
    issuer: str
    subject: str
    scope_id: str
    session_id: UUID


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    issuer: str,
    subject: str,
    scope_id: str,
    correlation_id: str,
) -> tuple[str, PrincipalContext] | None:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    auth_session_id = uuid4()
    audit_id = uuid4()

    def create(session: Session) -> tuple[str, PrincipalContext] | None:
        principal = session.scalar(
            select(AuthPrincipal).where(
                AuthPrincipal.issuer == issuer,
                AuthPrincipal.subject == subject,
                AuthPrincipal.scope_id == scope_id,
                AuthPrincipal.active.is_(True),
            )
        )
        if principal is None:
            session.add(
                SecurityAuditEvent(
                    id=audit_id,
                    actor_subject=None,
                    scope_id=None,
                    action="auth.login",
                    target_type="principal",
                    target_id=None,
                    result="denied",
                    correlation_id=correlation_id,
                )
            )
            return None
        auth_session = AuthSession(
            id=auth_session_id,
            principal_id=principal.id,
            token_hash=token_digest(token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.auth_session_ttl_seconds),
        )
        session.add(auth_session)
        session.add(
            SecurityAuditEvent(
                id=audit_id,
                actor_subject=principal.subject,
                scope_id=principal.scope_id,
                action="auth.login",
                target_type="session",
                target_id=str(auth_session.id),
                result="succeeded",
                correlation_id=correlation_id,
            )
        )
        return token, PrincipalContext(
            principal.issuer, principal.subject, principal.scope_id, auth_session.id
        )

    return run_database_unit(session_factory, create)


def get_principal(
    session_factory: sessionmaker[Session],
    settings: Settings,
    token: str | None,
) -> PrincipalContext | None:
    if token is None or len(token) > 100 or not token.isascii():
        return None
    digest = token_digest(token)
    now = datetime.now(UTC)
    with session_factory() as session:
        row = session.execute(
            select(AuthSession, AuthPrincipal)
            .join(AuthPrincipal, AuthPrincipal.id == AuthSession.principal_id)
            .where(
                AuthSession.token_hash == digest,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
                AuthPrincipal.active.is_(True),
                AuthPrincipal.issuer == settings.auth_issuer_url,
                AuthPrincipal.subject == settings.auth_allowed_subject,
                AuthPrincipal.scope_id == settings.auth_personal_scope_id,
            )
        ).first()
        if row is None:
            return None
        auth_session, principal = row
        return PrincipalContext(
            principal.issuer, principal.subject, principal.scope_id, auth_session.id
        )


def revoke_session(
    session_factory: sessionmaker[Session],
    context: PrincipalContext,
    *,
    correlation_id: str,
) -> None:
    now = utc_now()
    audit_id = uuid4()

    def revoke(session: Session) -> None:
        session.execute(
            update(AuthSession)
            .where(
                AuthSession.id == context.session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        session.add(
            SecurityAuditEvent(
                id=audit_id,
                actor_subject=context.subject,
                scope_id=context.scope_id,
                action="auth.logout",
                target_type="session",
                target_id=str(context.session_id),
                result="succeeded",
                correlation_id=correlation_id,
            )
        )

    run_database_unit(session_factory, revoke)
