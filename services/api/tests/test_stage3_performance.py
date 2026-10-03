"""Synthetic checks for Stage 3 Decimal return methods and bounded solving."""

from datetime import date
from decimal import Decimal

from app.domains.performance import (
    ExternalFlow,
    ValuationPoint,
    chained_modified_dietz,
    money_weighted_return,
)


def test_flat_market_deposit_is_not_reported_as_performance() -> None:
    points = [
        ValuationPoint(date(2026, 1, 1), Decimal("1000")),
        ValuationPoint(date(2026, 2, 1), Decimal("1500")),
    ]
    flows = [ExternalFlow(date(2026, 1, 16), Decimal("500"))]
    assert chained_modified_dietz(points, flows) == Decimal(0)


def test_xirr_returns_known_annualized_result() -> None:
    result, status = money_weighted_return(
        Decimal("100"),
        Decimal("110"),
        [],
        date(2026, 1, 1),
        date(2027, 1, 1),
    )
    assert status == "converged"
    assert result is not None
    assert abs(result - Decimal("0.10")) < Decimal("0.000001")


def test_multiple_mwr_sign_changes_are_not_guessed() -> None:
    result, status = money_weighted_return(
        Decimal("100"),
        Decimal("110"),
        [
            ExternalFlow(date(2026, 4, 1), Decimal("-200")),
            ExternalFlow(date(2026, 8, 1), Decimal("50")),
        ],
        date(2026, 1, 1),
        date(2027, 1, 1),
    )
    assert result is None
    assert status == "ambiguous_multiple_roots"


def test_same_day_flows_are_net_before_mwr_sign_change_analysis() -> None:
    _result, status = money_weighted_return(
        Decimal("100"),
        Decimal("110"),
        [
            ExternalFlow(date(2026, 4, 1), Decimal("-200")),
            ExternalFlow(date(2026, 4, 1), Decimal("50")),
        ],
        date(2026, 1, 1),
        date(2027, 1, 1),
    )
    assert status != "ambiguous_multiple_roots"


def test_modified_dietz_requires_positive_opening_value_and_period() -> None:
    assert (
        chained_modified_dietz(
            [
                ValuationPoint(date(2026, 1, 1), Decimal("0")),
                ValuationPoint(date(2026, 2, 1), Decimal("100")),
            ],
            [],
        )
        is None
    )
