"""Pure Decimal decomposition. Actual ETF ownership is replaced only in this view."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, localcontext
from typing import Any

VERSION = "one-level-usd/1"


def calculate(inputs: dict[str, Any]) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 80
        return _calculate(inputs)


def _calculate(inputs: dict[str, Any]) -> dict[str, Any]:
    positions = inputs["owned"]
    funds = inputs["funds"]
    nav = sum(
        (Decimal(p["value"]) for p in positions if p["status"] == "valued"), Decimal(0)
    )
    incomplete = any(p["status"] != "valued" for p in positions) or bool(
        inputs["warnings"]
    )
    signed = any(Decimal(p["value"]) < 0 for p in positions if p["status"] == "valued")
    percentages = nav > 0 and (not signed) and (not incomplete)
    contributions: list[dict[str, Any]] = []
    warnings = list(inputs["warnings"])

    def add(
        p: dict[str, Any],
        amount: Decimal,
        category: str,
        security: dict[str, Any] | None = None,
        composition: dict[str, Any] | None = None,
        weight: str | None = None,
        raw_name: str | None = None,
    ) -> None:
        if len(contributions) >= 50000:
            raise ValueError(
                "Calculation exceeds 50,000 contribution limit; select fewer accounts"
            )
        contributions.append(
            {
                "account_id": p["account_id"],
                "account_name": p["account_name"],
                "position_id": p["position_id"],
                "position_snapshot_id": p["position_snapshot_id"],
                "position_as_of": p["position_as_of"],
                "position_source": p["position_source"],
                "position_quality": p["position_quality"],
                "owned_security_id": p["security_id"],
                "owned_label": p["label"],
                "security_id": security["id"] if security else None,
                "issuer_id": security.get("issuer_id") if security else None,
                "issuer_name": security.get("issuer_name") if security else None,
                "label": security["label"]
                if security
                else raw_name or category.replace("_", " ").title(),
                "category": category,
                "amount": str(amount),
                "weight": weight,
                "quote_id": p["quote_id"],
                "quote_as_of": p["quote_as_of"],
                "quote_source": p["quote_source"],
                "quality_status": p["quality_status"],
                "fund_snapshot_id": composition["id"] if composition else None,
                "fund_as_of": composition["as_of"] if composition else None,
                "fund_fetched_at": composition["fetched_at"] if composition else None,
                "fund_source": composition["source"] if composition else None,
                "fund_source_url": composition["source_url"] if composition else None,
                "fund_quality": composition["quality_status"] if composition else None,
                "fund_stale": composition["stale"] if composition else False,
            }
        )

    for p in positions:
        if p["status"] != "valued":
            continue
        value = Decimal(p["value"])
        if p["security_type"] == "equity":
            add(p, value, "direct", p["security"])
        elif p["security_type"] == "cash":
            add(p, value, "cash")
        elif p["security_type"] == "etf":
            composition = funds.get(p["security_id"])
            if not composition or composition["quality_status"] == "opaque":
                add(p, value, "opaque_fund", composition=composition)
                warnings.append(f"{p['label']}: missing or unsupported composition")
                continue
            if composition["stale"]:
                warnings.append(
                    f"{p['label']}: stale composition as of {composition['as_of']}"
                )
            total = Decimal(0)
            for line in composition["lines"]:
                w = Decimal(line["weight"])
                total += w
                security = line["security"]
                if (
                    line["asset_type"] == "equity"
                    and security
                    and (security["type"] == "equity")
                ):
                    category = "indirect"
                elif line["asset_type"] == "cash":
                    category = "cash"
                elif line["asset_type"] == "nested" or (
                    security and security["type"] == "etf"
                ):
                    category = "nested_fund"
                else:
                    category = "unknown_other"
                add(
                    p,
                    value * w,
                    category,
                    security if category == "indirect" else None,
                    composition,
                    line["weight"],
                    line["raw_name"],
                )
            if total > 1 or any(
                Decimal(fund_line["weight"]) < 0 for fund_line in composition["lines"]
            ):
                raise ValueError("Unsupported fund bypassed opaque validation")
            add(
                p,
                value * (1 - total),
                "missing_weight",
                composition=composition,
                weight=str(1 - total),
            )
        else:
            add(p, value, "unknown_other")
    if len(contributions) > 50000:
        raise ValueError(
            "Calculation exceeds 50,000 contribution limit; select fewer accounts"
        )
    decomposition = sum((Decimal(c["amount"]) for c in contributions), Decimal(0))
    if decomposition != nav:
        raise ValueError("Exposure reconciliation failed; report unavailable")
    rows: dict[str, dict[str, Any]] = {}
    issuer_rows: dict[str, dict[str, Any]] = {}
    categories: dict[str, Decimal] = defaultdict(Decimal)
    attributed = Decimal(0)
    issuer_attributed = Decimal(0)
    for c in contributions:
        amount = Decimal(c["amount"])
        categories[c["category"]] += amount
        if c["category"] not in {"direct", "indirect"}:
            continue
        attributed += amount
        identity = c["security_id"]
        row = rows.setdefault(
            identity,
            {
                "id": identity,
                "label": c["label"],
                "direct": Decimal(0),
                "indirect": Decimal(0),
                "total": Decimal(0),
                "contributions": [],
            },
        )
        row[c["category"]] += amount
        row["total"] += amount
        row["contributions"].append(c)
        issuer = c["issuer_id"]
        if issuer:
            issuer_attributed += amount
            r = issuer_rows.setdefault(
                issuer,
                {
                    "id": issuer,
                    "label": c["issuer_name"],
                    "direct": Decimal(0),
                    "indirect": Decimal(0),
                    "total": Decimal(0),
                    "contributions": [],
                },
            )
            r[c["category"]] += amount
            r["total"] += amount
            r["contributions"].append(c)

    def export_rows(values: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for row in sorted(values.values(), key=lambda r: (-r["total"], r["id"])):
            result.append(
                {
                    **row,
                    "direct": str(row["direct"]),
                    "indirect": str(row["indirect"]),
                    "total": str(row["total"]),
                    "percentage": str(row["total"] / nav * 100)
                    if percentages
                    else None,
                    "included_valued_percentage": str(row["total"] / nav * 100)
                    if nav > 0 and (not signed)
                    else None,
                }
            )
        return result

    return {
        "calculation_version": VERSION,
        "reporting_currency": "USD",
        "included_valued_nav": str(nav),
        "total_portfolio_nav": str(nav) if not incomplete else None,
        "nav_status": "incomplete" if incomplete else "complete",
        "percentages_available": percentages,
        "security_coverage": str(attributed / nav * 100) if percentages else None,
        "issuer_coverage": str(issuer_attributed / nav * 100) if percentages else None,
        "attribution_numerator": str(attributed),
        "issuer_attribution_numerator": str(issuer_attributed),
        "issuer_unmapped_value": str(attributed - issuer_attributed),
        "coverage_denominator": str(nav),
        "categories": {k: str(v) for (k, v) in sorted(categories.items())},
        "reconciled": True,
        "security_rows": export_rows(rows),
        "issuer_rows": export_rows(issuer_rows),
        "contributions": contributions,
        "owned": positions,
        "warnings": sorted(
            set(
                warnings
                + (
                    ["Signed allocations: percentages unavailable"]
                    if signed or nav <= 0
                    else []
                )
            )
        ),
    }
