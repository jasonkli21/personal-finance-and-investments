"""Bounded local catalog search; no external provider calls."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Security


def resolve_securities(session: Session, query: str) -> list[Security]:
    normalized = query.strip()
    if len(normalized) < 2:
        return []
    ticker_prefix = normalized.upper().replace("%", "\\%").replace("_", "\\_")
    name_pattern = normalized.replace("%", "\\%").replace("_", "\\_")
    statement = (
        select(Security)
        .where(
            Security.display_ticker.like(f"{ticker_prefix}%", escape="\\")
            | func.lower(Security.name).like(f"%{name_pattern.lower()}%", escape="\\")
        )
        .order_by(Security.display_ticker, Security.name, Security.id)
        .limit(11)
    )
    return list(session.scalars(statement))
