"""Frozen calculation API and formula-safe, source-traceable CSV export."""

import csv
import io
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.api.contracts import (
    ExposureRowRead,
    OwnedReportLine,
    ReportContribution,
    ReportCreate,
    ReportPage,
    ReportSummary,
)
from app.api.routes import SessionDependency
from app.domains import reports

router = APIRouter(prefix="/v1/portfolio")
View = Literal["owned", "security", "issuer"]


def load(
    request: Request, session: SessionDependency, identifier: UUID
) -> dict[str, Any]:
    try:
        return reports.read(session, request.app.state.file_store, identifier)
    except reports.ReportNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail="Frozen report unavailable; create a new report.",
        ) from exc


@router.post("/reports", response_model=ReportSummary)
def create(request: Request, data: ReportCreate) -> ReportSummary:
    try:
        report = reports.create(
            request.app.state.session_factory,
            request.app.state.file_store,
            account_ids=data.account_ids,
            as_of=data.as_of,
            include_archived=data.include_archived,
        )
        return ReportSummary.model_validate(report)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/reports/{identifier}", response_model=ReportSummary)
def summary(
    request: Request, session: SessionDependency, identifier: UUID
) -> ReportSummary:
    return ReportSummary.model_validate(load(request, session, identifier))


def filtered(
    report: dict[str, Any], view: View, q: str, source: str
) -> list[dict[str, Any]]:
    rows = report["owned"] if view == "owned" else report[f"{view}_rows"]
    return [
        row
        for row in rows
        if q.casefold() in row["label"].casefold()
        and (
            not source
            or any(
                source.casefold() in str(row.get(field) or "").casefold()
                for field in ("quote_source", "position_source")
            )
            or any(
                any(
                    source.casefold() in str(c.get(field) or "").casefold()
                    for field in ("fund_source", "quote_source", "position_source")
                )
                for c in row.get("contributions", [])
            )
        )
    ]


@router.get("/reports/{identifier}/rows", response_model=ReportPage)
def rows(
    request: Request,
    session: SessionDependency,
    identifier: UUID,
    view: View = "security",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    q: Annotated[str, Query(max_length=200)] = "",
    source: Annotated[str, Query(max_length=100)] = "",
    sort: Literal["label", "value"] = "value",
    descending: bool = True,
) -> ReportPage:
    selected = filtered(load(request, session, identifier), view, q, source)
    selected.sort(key=lambda r: str(r.get("id") or r.get("position_id")))
    selected.sort(
        key=lambda r: (
            r["label"].casefold()
            if sort == "label"
            else Decimal(r.get("total") or r.get("value") or "0")
        ),
        reverse=descending,
    )
    return ReportPage(
        calculation_id=identifier,
        view=view,
        total_rows=len(selected),
        offset=offset,
        limit=limit,
        rows=[
            OwnedReportLine.model_validate(row)
            if view == "owned"
            else ExposureRowRead.model_validate(row)
            for row in selected[offset : offset + limit]
        ],
    )


@router.get(
    "/reports/{identifier}/breakdown/{target}", response_model=list[ReportContribution]
)
def breakdown(
    request: Request,
    session: SessionDependency,
    identifier: UUID,
    target: str,
    level: Literal["security", "issuer", "category"] = "security",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReportContribution]:
    report = load(request, session, identifier)
    selected = (
        [
            c
            for c in report["contributions"]
            if (c["category"] in {"direct", "indirect"} and not c["issuer_id"])
        ]
        if level == "category" and target == "issuer_unmapped"
        else [
            c
            for c in report["contributions"]
            if c["category" if level == "category" else f"{level}_id"] == target
        ]
    )
    if not selected:
        raise HTTPException(
            status_code=404, detail="Exposure row not found in frozen report"
        )
    return [
        ReportContribution.model_validate(c) for c in selected[offset : offset + limit]
    ]


def text_cell(value: object) -> str:
    text = str(value or "")
    return (
        "'" + text
        if text.lstrip().startswith(("=", "+", "-", "@"))
        or text.startswith(("\t", "\r", "\n"))
        else text
    )


@router.get("/reports/{identifier}/export")
def export(
    request: Request,
    session: SessionDependency,
    identifier: UUID,
    view: View = "security",
    q: Annotated[str, Query(max_length=200)] = "",
    source: Annotated[str, Query(max_length=100)] = "",
) -> Response:
    report = load(request, session, identifier)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        [
            "calculation_id",
            "calculation_version",
            "view",
            "label",
            "category",
            "value",
            "direct",
            "indirect",
            "percentage_of_total_portfolio",
            "currency",
            "accounts",
            "position_as_of",
            "quote_as_of",
            "fund_as_of",
            "source",
            "quality",
            "included_valued_nav",
            "nav_status",
            "position_snapshot_ids",
            "quote_ids",
            "fund_snapshot_ids",
        ]
    )
    for row in filtered(report, view, q, source):
        contributions = row.get("contributions", [])
        writer.writerow(
            [
                str(identifier),
                report["calculation_version"],
                view,
                text_cell(row["label"]),
                text_cell(row.get("status", "exposure")),
                row.get("value") or row.get("total") or "",
                row.get("direct", ""),
                row.get("indirect", ""),
                row.get("percentage") or "",
                row.get("currency", "USD"),
                text_cell(
                    row.get("account_name")
                    or ";".join(sorted({c["account_name"] for c in contributions}))
                ),
                row.get("position_as_of")
                or ";".join(sorted({c["position_as_of"] for c in contributions})),
                row.get("quote_as_of")
                or ";".join(
                    sorted(
                        {c["quote_as_of"] for c in contributions if c["quote_as_of"]}
                    )
                ),
                ";".join(
                    sorted({c["fund_as_of"] for c in contributions if c["fund_as_of"]})
                ),
                text_cell(
                    row.get("quote_source")
                    or ";".join(
                        sorted(
                            {
                                c["fund_source"] or c["quote_source"] or ""
                                for c in contributions
                            }
                        )
                    )
                ),
                row.get("quality_status", "derived"),
                report["included_valued_nav"],
                report["nav_status"],
                row.get("position_snapshot_id")
                or ";".join(sorted({c["position_snapshot_id"] for c in contributions})),
                row.get("quote_id")
                or ";".join(
                    sorted({c["quote_id"] for c in contributions if c["quote_id"]})
                ),
                ";".join(
                    sorted(
                        {
                            c["fund_snapshot_id"]
                            for c in contributions
                            if c["fund_snapshot_id"]
                        }
                    )
                ),
            ]
        )
    if view != "owned":
        residuals = dict(report["categories"])
        if view == "issuer":
            residuals["issuer_unmapped"] = report["issuer_unmapped_value"]
        for category, value in residuals.items():
            if category not in {"direct", "indirect"}:
                evidence = [
                    c
                    for c in report["contributions"]
                    if (
                        c["category"] == category
                        if category != "issuer_unmapped"
                        else c["category"] in {"direct", "indirect"}
                        and not c["issuer_id"]
                    )
                ]

                def joined(field: str, records: list[dict[str, Any]] = evidence) -> str:
                    return ";".join(
                        sorted({str(c[field]) for c in records if c.get(field)})
                    )

                writer.writerow(
                    [
                        str(identifier),
                        report["calculation_version"],
                        view,
                        category,
                        category,
                        value,
                        "",
                        "",
                        "",
                        "USD",
                        text_cell(joined("account_name")),
                        joined("position_as_of"),
                        joined("quote_as_of"),
                        joined("fund_as_of"),
                        text_cell(
                            joined("fund_source")
                            or joined("quote_source")
                            or joined("position_source")
                        ),
                        text_cell(
                            joined("fund_quality")
                            or joined("quality_status")
                            or "derived"
                        ),
                        report["included_valued_nav"],
                        report["nav_status"],
                        joined("position_snapshot_id"),
                        joined("quote_id"),
                        joined("fund_snapshot_id"),
                    ]
                )
    return Response(
        content=stream.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="portfolio-{identifier}-{view}.csv"'
            )
        },
    )
