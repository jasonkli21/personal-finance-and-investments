"""Synthetic checks for Stage 3 Decimal return methods and bounded solving."""

from datetime import date
from decimal import Decimal, localcontext

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


def test_performance_math_does_not_inherit_caller_decimal_precision() -> None:
    points = [
        ValuationPoint(date(2026, 1, 1), Decimal("123.4567891234")),
        ValuationPoint(date(2026, 2, 1), Decimal("200.0000000001")),
        ValuationPoint(date(2027, 1, 1), Decimal("234.5678912345")),
    ]
    flows = [
        ExternalFlow(date(2026, 1, 16), Decimal("12.3456789123")),
        ExternalFlow(date(2026, 1, 16), Decimal("-0.0000000001")),
    ]
    expected_twr = chained_modified_dietz(points, flows)
    expected_mwr = money_weighted_return(
        points[0].value, points[-1].value, flows, points[0].as_of, points[-1].as_of
    )
    with localcontext() as context:
        context.prec = 8
        assert chained_modified_dietz(points, flows) == expected_twr
        assert (
            money_weighted_return(
                points[0].value,
                points[-1].value,
                flows,
                points[0].as_of,
                points[-1].as_of,
            )
            == expected_mwr
        )
