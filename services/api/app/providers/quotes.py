"""Offline quote observations behind a provider boundary; no network dependency."""

from datetime import UTC, datetime
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


def observation_time(value: datetime) -> datetime:
    """Treat timezone-less adapter timestamps as the persisted UTC convention."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def select_observation(
    provider: QuoteProvider,
    security_id: UUID,
    currency: str,
    valuation_at: datetime,
    *,
    reported_as_of: datetime | None,
    source_priority: list[str],
) -> Quote | None:
    """Choose a current accepted quote without displacing a newer line fallback.

    Owned valuations and frozen reports must use the same tie-breaking policy;
    otherwise cash-flow/net-worth views can disagree with portfolio reports.
    A reviewed override wins an equal timestamp, never an older timestamp.
    """
    observations = provider.observations(security_id, currency, valuation_at)
    if not observations:
        return None

    selected = min(
        observations,
        key=lambda quote: (
            -observation_time(quote.as_of).timestamp(),
            -bool(quote.provider_metadata.get("reviewed_override")),
            source_priority.index(quote.source)
            if quote.source in source_priority
            else len(source_priority),
            str(quote.id),
        ),
    )
    if reported_as_of is not None:
        quote_time = observation_time(selected.as_of)
        reported_time = observation_time(reported_as_of)
        if quote_time < reported_time or (
            quote_time == reported_time
            and not selected.provider_metadata.get("reviewed_override")
        ):
            return None
    return selected
