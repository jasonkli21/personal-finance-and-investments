"""Bounded Decimal performance calculations with explicit data sufficiency."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

PERFORMANCE_VERSION = "stage3-performance-v1"
MAX_ANNUAL_MWR = Decimal("10")
MIN_MWR = Decimal("-0.9999")


@dataclass(frozen=True)
class ValuationPoint:
    as_of: date
    value: Decimal


@dataclass(frozen=True)
class ExternalFlow:
    effective_date: date
    amount: Decimal


def modified_dietz(
    beginning: Decimal,
    ending: Decimal,
    flows: list[ExternalFlow],
    start: date,
    end: date,
) -> Decimal | None:
    """Return a period Modified Dietz estimate; flows are positive contributions."""
    days = (end - start).days
    if days <= 0 or beginning <= 0:
        return None
    with localcontext() as context:
        context.prec = 60
        total_flows = sum((flow.amount for flow in flows), Decimal(0))
        weighted_flows = sum(
            (
                flow.amount * Decimal((end - flow.effective_date).days) / Decimal(days)
                for flow in flows
            ),
            Decimal(0),
        )
        denominator = beginning + weighted_flows
        if denominator <= 0:
            return None
        return (ending - beginning - total_flows) / denominator


def chained_modified_dietz(
    points: list[ValuationPoint], flows: list[ExternalFlow]
) -> Decimal | None:
    """Chain Dietz subperiods at observed valuations; no missing marks are filled."""
    if len(points) < 2 or any(point.value <= 0 for point in points):
        return None
    growth = Decimal(1)
    for beginning, ending in zip(points, points[1:], strict=False):
        interval_flows = [
            flow
            for flow in flows
            if beginning.as_of < flow.effective_date <= ending.as_of
        ]
        period = modified_dietz(
            beginning.value,
            ending.value,
            interval_flows,
            beginning.as_of,
            ending.as_of,
        )
        if period is None or period <= -1:
            return None
        growth *= Decimal(1) + period
    return growth - Decimal(1)


def money_weighted_return(
    beginning: Decimal,
    ending: Decimal,
    flows: list[ExternalFlow],
    start: date,
    end: date,
) -> tuple[Decimal | None, str]:
    """Solve annualized XIRR by bounded bisection when one root is indicated."""
    if start >= end or beginning <= 0 or ending < 0:
        return None, "insufficient_inputs"
    # Investor-perspective cash flows: portfolio contributions are outflows.
    by_date: dict[date, Decimal] = {start: -beginning, end: ending}
    for flow in flows:
        if start < flow.effective_date <= end:
            by_date[flow.effective_date] = (
                by_date.get(flow.effective_date, Decimal(0)) - flow.amount
            )
    dated = sorted(by_date.items())
    signs = [1 if amount > 0 else -1 for _, amount in dated if amount != 0]
    sign_changes = sum(
        left != right for left, right in zip(signs, signs[1:], strict=False)
    )
    if sign_changes > 1:
        return None, "ambiguous_multiple_roots"
    if sign_changes == 0:
        return None, "no_root"

    with localcontext() as context:
        context.prec = 60

        def npv(rate: Decimal) -> Decimal:
            growth = Decimal(1) + rate
            return sum(
                (
                    amount / (growth ** (Decimal((when - start).days) / Decimal(365)))
                    for when, amount in dated
                ),
                Decimal(0),
            )

        low = MIN_MWR
        high = MAX_ANNUAL_MWR
        low_value = npv(low)
        high_value = npv(high)
        if low_value == 0:
            return low, "converged"
        if high_value == 0:
            return high, "converged"
        if (low_value > 0) == (high_value > 0):
            return None, "no_root_in_bounded_range"
        for _ in range(160):
            middle = (low + high) / Decimal(2)
            middle_value = npv(middle)
            if abs(middle_value) <= Decimal("1e-20"):
                return middle, "converged"
            if (middle_value > 0) == (low_value > 0):
                low, low_value = middle, middle_value
            else:
                high, high_value = middle, middle_value
            if high - low <= Decimal("1e-18"):
                return (low + high) / Decimal(2), "converged"
    return None, "not_converged"
