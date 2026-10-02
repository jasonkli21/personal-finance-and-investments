"""Offline quote observations behind a provider boundary; no network dependency."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Quote


class QuoteProvider(Protocol):
    def observations(
        self, security_id: UUID, currency: str, as_of: datetime
    ) -> list[Quote]:
        """Return accepted observations no later than the requested valuation."""
        ...


class CachedQuoteProvider:
    """Read manual and externally cached observations without fetching or writing."""

    def __init__(self, session: Session):
        self.session = session

    def observations(
        self, security_id: UUID, currency: str, as_of: datetime
    ) -> list[Quote]:
        rows = list(
            self.session.scalars(
                select(Quote)
                .where(
                    Quote.security_id == security_id,
                    Quote.currency == currency,
                    Quote.as_of <= as_of,
                    Quote.quality_status.in_(
                        ("reviewed", "reported", "manual", "synthetic")
                    ),
                )
                .order_by(Quote.as_of.desc())
                .limit(10001)
            )
        )
        if len(rows) > 10000:
            raise ValueError("Quote history exceeds safe capture limit")
        return rows


class ManualQuoteProvider(CachedQuoteProvider):
    """Read explicitly reviewed manual observations from the same offline store."""

    def observations(
        self, security_id: UUID, currency: str, as_of: datetime
    ) -> list[Quote]:
        return [
            row
            for row in super().observations(security_id, currency, as_of)
            if row.provider_metadata.get("reviewed_override")
        ]
