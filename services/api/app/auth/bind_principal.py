"""Dry-run or explicitly bind the one approved personal data scope."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.db.models import AuthPrincipal, Base


def bind_principal(
    session: Session, *, issuer: str, subject: str, scope_id: str
) -> str:
    """Create one personal mapping or accept the identical mapping as a no-op."""
    current = list(session.scalars(select(AuthPrincipal)))
    if not current:
        session.add(
            AuthPrincipal(
                id=uuid4(),
                issuer=issuer,
                subject=subject,
                scope_id=scope_id,
                active=True,
            )
        )
        return "created"
    if (
        len(current) == 1
        and current[0].issuer == issuer
        and current[0].subject == subject
        and current[0].scope_id == scope_id
        and current[0].active
    ):
        return "already_bound"
    raise ValueError("Refusing to replace an existing principal or bind another scope.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write the principal binding"
    )
    args = parser.parse_args()
    settings = load_settings()
    if (
        not settings.auth_issuer_url
        or not settings.auth_allowed_subject
        or not settings.auth_personal_scope_id
    ):
        raise SystemExit(
            "Set AUTH_ISSUER_URL, AUTH_ALLOWED_SUBJECT and AUTH_PERSONAL_SCOPE_ID "
            "before binding."
        )
    engine = DatabaseEngineFactory.create(settings, purpose="application")
    counts: dict[str, int] = {}
    try:
        with Session(engine) as session:
            for table in Base.metadata.sorted_tables:
                if table.name in {
                    "auth_principals",
                    "auth_sessions",
                    "security_audit_events",
                }:
                    continue
                counts[table.name] = int(
                    session.scalar(select(func.count()).select_from(table)) or 0
                )
            current = list(session.scalars(select(AuthPrincipal)))
            proposed = {
                "subject": settings.auth_allowed_subject,
                "issuer": settings.auth_issuer_url,
                "scope_id": settings.auth_personal_scope_id,
                "records": counts,
                "apply": args.apply,
                "existing_binding": (
                    "none"
                    if not current
                    else "same"
                    if len(current) == 1
                    and current[0].subject == settings.auth_allowed_subject
                    and current[0].issuer == settings.auth_issuer_url
                    and current[0].scope_id == settings.auth_personal_scope_id
                    and current[0].active
                    else "different"
                ),
            }
            print(json.dumps(proposed, sort_keys=True))
            if not args.apply:
                return
            session.rollback()
            with session.begin():
                outcome = bind_principal(
                    session,
                    issuer=settings.auth_issuer_url,
                    subject=settings.auth_allowed_subject,
                    scope_id=settings.auth_personal_scope_id,
                )
            print(json.dumps({"binding": outcome}, sort_keys=True))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
