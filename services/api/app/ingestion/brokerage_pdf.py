"""Deterministic parser for text statements with a holdings table."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PDF_PARSER_VERSION = "brokerage-text-pdf/1"
_DIGITS = r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)"
_NUMBER = re.compile(
    rf"^(?:-?\$?{_DIGITS}(?:\.[0-9]+)?|\(\$?{_DIGITS}(?:\.[0-9]+)?\))$"
)
_HEADER_ALIASES = {
    "identifier": {"ticker", "symbol", "ticker symbol", "security symbol"},
    "name": {"security", "description", "security name", "investment"},
    "quantity": {"quantity", "shares", "qty"},
    "price": {"price", "last price", "unit price"},
    "reported_value": {"market value", "value", "current value"},
    "currency": {"currency", "currency code"},
}
_REQUIRED_HEADER_FIELDS = set(_HEADER_ALIASES) - {"currency"}
_STATEMENT_DATE = re.compile(
    r"\b(?:as\s+of|statement\s+date|period\s+ending)\s*:?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b",
    re.IGNORECASE,
)


class PdfExtractionError(ValueError):
    """Safe local parser failure code suitable for an HTTP response."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _worker_path() -> Path:
    return Path(__file__).with_name("pdf_worker.py")


def extract_pdf_pages(
    content: bytes, *, timeout_seconds: int = 8, max_pages: int = 40
) -> list[dict[str, Any]]:
    if not content.startswith(b"%PDF-"):
        raise PdfExtractionError("pdf_invalid")
    try:
        # Uploaded PDFs are untrusted parser input. Do not expose the API
        # process's database/AWS credentials or other secrets to the parser
        # subprocess. The worker needs only its page bound; Windows additionally
        # needs SystemRoot to start a child process reliably.
        child_environment = {"PDF_MAX_PAGES": str(max_pages)}
        if os.name == "nt" and os.environ.get("SYSTEMROOT"):
            child_environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        completed = subprocess.run(
            [sys.executable, str(_worker_path())],
            input=content,
            env=child_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfExtractionError("parser_timeout") from exc
    if completed.returncode != 0 or len(completed.stdout) > 4_000_000:
        raise PdfExtractionError("pdf_unreadable")
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PdfExtractionError("pdf_unreadable") from exc
    if not isinstance(payload, dict):
        raise PdfExtractionError("pdf_unreadable")
    if "error" in payload:
        raise PdfExtractionError(str(payload["error"]))
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise PdfExtractionError("pdf_unreadable")
    return pages


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"\s{2,}|\s*\|\s*", line.strip())]


def _header_fields(line: str) -> list[str] | None:
    fields = _cells(line)
    mapped: list[str] = []
    for field in fields:
        key = " ".join(field.casefold().split())
        match = next(
            (
                canonical
                for canonical, aliases in _HEADER_ALIASES.items()
                if key in aliases
            ),
            None,
        )
        if match is None:
            return None
        mapped.append(match)
    if (
        not _REQUIRED_HEADER_FIELDS.issubset(mapped)
        or len(mapped) not in {len(_REQUIRED_HEADER_FIELDS), len(_HEADER_ALIASES)}
        or len(set(mapped)) != len(mapped)
    ):
        return None
    return mapped


def _amount_is_valid(raw: str) -> bool:
    return bool(_NUMBER.fullmatch(raw.replace(" ", "")))


def _normalized_amount(raw: str) -> str:
    value = raw.strip().replace("$", "").replace(",", "")
    if value.startswith("(") and value.endswith(")"):
        return f"-{value[1:-1]}"
    return value


def _statement_date(text: str) -> date | None:
    match = _STATEMENT_DATE.search(text)
    if match is None:
        return None
    raw = match.group(1)
    try:
        if "-" in raw:
            return date.fromisoformat(raw)
        month, day, year = (int(part) for part in raw.split("/"))
        return date(year, month, day)
    except ValueError:
        return None


def parse_brokerage_pdf(
    content: bytes,
    *,
    currency: str,
    timeout_seconds: int = 8,
    max_pages: int = 40,
    max_rows: int = 5000,
    effective_date: date | None = None,
) -> tuple[bytes, dict[str, Any]]:
    pages = extract_pdf_pages(
        content, timeout_seconds=timeout_seconds, max_pages=max_pages
    )
    fields: list[str] | None = None
    header_page: int | None = None
    records: list[dict[str, str]] = []
    unparsed_count = 0
    row_index = 0
    currency_assumed = False
    document_text = "\n".join(
        str(page.get("text", "")) for page in pages if isinstance(page, dict)
    )
    date_candidate = _statement_date(document_text)
    date_review_required = date_candidate is None or (
        effective_date is not None and date_candidate != effective_date
    )

    for page in pages:
        page_number = int(page["page"])
        text = page.get("text")
        if not isinstance(text, str):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if fields is None:
                found = _header_fields(line)
                if found is not None:
                    fields, header_page = found, page_number
                    currency_assumed = "currency" not in found
                continue
            if _header_fields(line) is not None:
                continue
            if not line.strip() or re.fullmatch(r"[\s\-_=]+", line):
                continue
            cells = _cells(line)
            source_evidence = f"page:{page_number}:line:{line_number}"
            row_index += 1
            if row_index > max_rows:
                raise PdfExtractionError("row_limit")
            values = dict(zip(fields, cells, strict=False))
            is_position = (
                len(cells) == len(fields)
                and _amount_is_valid(values.get("quantity", ""))
                and (
                    not values.get("price") or _amount_is_valid(values.get("price", ""))
                )
                and (
                    not values.get("reported_value")
                    or _amount_is_valid(values.get("reported_value", ""))
                )
                and bool(values.get("identifier") or values.get("name"))
            )
            if not is_position:
                unparsed_count += 1
                values = {
                    "identifier": "",
                    "name": "",
                    "quantity": "",
                    "price": "",
                    "reported_value": "",
                }
            identifier = values.get("identifier", "")
            name = values.get("name", "")
            quantity = _normalized_amount(values.get("quantity", ""))
            price = _normalized_amount(values.get("price", ""))
            reported_value = _normalized_amount(values.get("reported_value", ""))
            discrepancy = ""
            if is_position:
                if price and reported_value:
                    try:
                        calculated = Decimal(quantity) * Decimal(price)
                        reported = Decimal(reported_value)
                        if abs(calculated - reported) > Decimal("0.02"):
                            discrepancy = (
                                "Reported value differs from quantity × price."
                            )
                    except (InvalidOperation, ValueError):
                        discrepancy = "Reported value could not be reconciled."
                elif not price and "cash" not in name.casefold():
                    discrepancy = "Price is missing; the position needs review."
                elif not reported_value:
                    discrepancy = (
                        "Reported value is missing; the position needs review."
                    )
            warnings = [
                warning
                for warning in (
                    discrepancy,
                    "Unparsed source row." if not is_position else "",
                    "Currency column absent; account currency was assumed."
                    if currency_assumed
                    else "",
                    "Statement date is missing; confirm the selected snapshot date."
                    if date_candidate is None
                    else "Statement date differs from the selected snapshot date."
                    if effective_date is not None and date_candidate != effective_date
                    else "",
                )
                if warning
            ]
            records.append(
                {
                    "identifier": identifier,
                    "name": name,
                    "quantity": quantity,
                    "price": price,
                    "currency": values.get("currency", "") or currency,
                    "asset_type": "statement_needs_review" if warnings else "",
                    "reported_value": reported_value,
                    "source_evidence": source_evidence,
                    "source_text": line[:2000],
                    "source_warning": " ".join(warnings),
                }
            )

    if fields is None or header_page is None:
        raise PdfExtractionError("holdings_table_not_found")
    if not records:
        raise PdfExtractionError("no_position_rows")

    output = io.StringIO(newline="")
    columns = [
        "identifier",
        "name",
        "quantity",
        "price",
        "currency",
        "asset_type",
        "reported_value",
        "source_evidence",
        "source_text",
        "source_warning",
    ]
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    diagnostics = {
        "parser": PDF_PARSER_VERSION,
        "page_count": len(pages),
        "table_page": header_page,
        "row_count": len(records),
        "unparsed_rows": unparsed_count,
        "currency_assumed_from_account": currency_assumed,
        "statement_date_candidate": date_candidate.isoformat()
        if date_candidate
        else None,
        "statement_date_review_required": date_review_required,
        "review_required": True,
        "pdf_has_no_text_layer": False,
    }
    return output.getvalue().encode("utf-8"), diagnostics


async def parse_brokerage_pdf_async(
    content: bytes,
    *,
    currency: str,
    timeout_seconds: int = 8,
    max_pages: int = 40,
    max_rows: int = 5000,
    effective_date: date | None = None,
) -> tuple[bytes, dict[str, Any]]:
    return await asyncio.to_thread(
        parse_brokerage_pdf,
        content,
        currency=currency,
        timeout_seconds=timeout_seconds,
        max_pages=max_pages,
        max_rows=max_rows,
        effective_date=effective_date,
    )
