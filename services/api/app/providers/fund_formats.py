"""Deterministic, bounded official-download and user CSV parsers (no network)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Protocol
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from app.domains.imports import InvalidCsv

SOURCES = {
    "ishares": (
        "IVV",
        "https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf",
    ),
    "spdr": (
        "SPY",
        "https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy",
    ),
}


@dataclass(frozen=True)
class ParsedFund:
    as_of: date
    parser_version: str
    source_url: str | None
    rows: list[dict[str, str]]
    mapping: dict[str, str]
    weight_unit: str


class FundHoldingsProvider(Protocol):
    def parse(
        self,
        content: bytes,
        *,
        ticker: str,
        as_of: date,
        mapping: dict[str, str],
        weight_unit: str,
        max_rows: int,
    ) -> ParsedFund: ...


def weight(raw: str, unit: str) -> Decimal:
    value = raw.strip().removesuffix("%").replace(",", "")
    if (
        unit not in {"percent", "decimal"}
        or not re.fullmatch(r"-?\d+(?:\.\d{1,10})?", value)
        or len(value) > 30
    ):
        raise ValueError(
            "Weight needs a finite plain decimal and explicit percent/decimal unit"
        )
    with localcontext() as context:
        context.prec = 80
        result = Decimal(value) / (100 if unit == "percent" else 1)
        if abs(result) >= Decimal("1e8") or result != result.quantize(Decimal("1e-10")):
            raise ValueError("Weight exceeds NUMERIC(18,10) precision")
    return result


def _date(value: str) -> date:
    for fmt in ("%b %d, %Y", "%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip().removeprefix("As of "), fmt).date()
        except ValueError:
            pass
    raise InvalidCsv("Missing or invalid holdings-effective date")


def _records(content: bytes, max_rows: int) -> list[list[str]]:
    if (
        not content
        or b"\0" in content
        or content.lstrip().lower().startswith((b"<html", b"<!doctype"))
    ):
        raise InvalidCsv("Upload a UTF-8 CSV, not binary/HTML content")
    try:
        records: list[list[str]] = []
        reader = csv.reader(io.StringIO(content.decode("utf-8-sig")), strict=True)
        # Bound metadata/blank lines as well as holdings before materializing
        # the entire upload. A small file of newlines can otherwise allocate
        # millions of Python lists before the holdings-row limit is checked.
        for row in reader:
            if len(records) >= max_rows + 100:
                raise InvalidCsv("CSV exceeds configured row limit")
            records.append(row)
        return records
    except (UnicodeError, csv.Error) as exc:
        raise InvalidCsv("Malformed UTF-8 CSV") from exc


def _xlsx(content: bytes, max_rows: int) -> list[list[str]]:
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > 100 or sum(f.file_size for f in infos) > 20_000_000:
                raise InvalidCsv("Workbook exceeds safe uncompressed limits")

            def xml(path: str) -> ET.Element:
                data = archive.read(path)
                if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                    raise InvalidCsv("Workbook XML declarations are unsupported")
                return ET.fromstring(data)

            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = [
                    "".join(s.itertext())
                    for s in xml("xl/sharedStrings.xml").findall("x:si", ns)
                ]
            rows: list[list[str]] = []
            for row in xml("xl/worksheets/sheet1.xml").findall(".//x:row", ns):
                if len(rows) >= max_rows + 100:
                    raise InvalidCsv("Workbook exceeds configured row limit")
                values: list[str] = []
                for cell in row.findall("x:c", ns):
                    if cell.find("x:f", ns) is not None:
                        raise InvalidCsv("Formula cells are unsupported")
                    letters = re.sub(r"\d", "", cell.attrib.get("r", "A1"))
                    index = 0
                    for letter in letters:
                        index = index * 26 + ord(letter) - 64
                    if not 1 <= index <= 100:
                        raise InvalidCsv("Workbook has excessive columns")
                    while len(values) < index:
                        values.append("")
                    value = cell.findtext("x:v", default="", namespaces=ns)
                    if cell.attrib.get("t") == "s":
                        string_index = int(value)
                        if not 0 <= string_index < len(strings):
                            raise InvalidCsv("Workbook string reference is invalid")
                        value = strings[string_index]
                    elif cell.attrib.get("t") == "inlineStr":
                        inline = cell.find("x:is", ns)
                        if inline is None:
                            raise InvalidCsv("Workbook inline string is missing")
                        value = "".join(inline.itertext())
                    values[index - 1] = value
                rows.append(values)
            return rows
    except (
        BadZipFile,
        KeyError,
        ET.ParseError,
        IndexError,
        ValueError,
        RuntimeError,
        NotImplementedError,
    ) as exc:
        raise InvalidCsv("Invalid supported SPDR workbook") from exc


def parse_fund(
    content: bytes,
    *,
    format_id: str,
    ticker: str,
    as_of: date,
    mapping: dict[str, str],
    weight_unit: str,
    max_rows: int,
) -> ParsedFund:
    if format_id not in {"manual", "ishares", "spdr"}:
        raise InvalidCsv("Unsupported fund format")
    records = (
        _xlsx(content, max_rows) if format_id == "spdr" else _records(content, max_rows)
    )
    header_index = 0
    source_url = None
    if format_id == "ishares":
        if not records or records[0] != ["iShares Core S&P 500 ETF"] or ticker != "IVV":
            raise InvalidCsv("This iShares format supports IVV fund holdings only")
        dates = [
            r[1] for r in records[:30] if len(r) >= 2 and r[0] == "Fund Holdings as of"
        ]
        if not dates or _date(dates[0]) != as_of:
            raise InvalidCsv("Confirmed date differs from issuer effective date")
        header_index = next(
            (
                i
                for i, r in enumerate(records[:30])
                if "Weight (%)" in r and "Asset Class" in r
            ),
            -1,
        )
        mapping = {
            "identifier": "Ticker",
            "name": "Name",
            "weight": "Weight (%)",
            "asset_type": "Asset Class",
            "exchange": "Exchange",
        }
        weight_unit = "percent"
        source_url = SOURCES[format_id][1]
    elif format_id == "spdr":
        metadata = {r[0]: r[1] for r in records[:4] if len(r) >= 2}
        if (
            ticker != "SPY"
            or metadata.get("Ticker Symbol:") != "SPY"
            or "SPDR" not in metadata.get("Fund Name:", "")
            or _date(metadata.get("Holdings:", "")) != as_of
        ):
            raise InvalidCsv(
                "Workbook fund identity/effective date differs from SPY confirmation"
            )
        header_index = next(
            (
                i
                for i, r in enumerate(records[:20])
                if "Weight" in r and "Ticker" in r and "Identifier" in r
            ),
            -1,
        )
        mapping = {
            "identifier": "Ticker",
            "name": "Name",
            "weight": "Weight",
            "cusip": "Identifier",
        }
        weight_unit = "percent"
        source_url = SOURCES[format_id][1]
    if header_index < 0 or not records:
        raise InvalidCsv("Issuer headers changed; review the source format")
    headers = [v.strip() for v in records[header_index]]
    if (
        not 1 <= len(headers) <= 100
        or len(set(headers)) != len(headers)
        or any(not v for v in headers)
    ):
        raise InvalidCsv("CSV header columns must be non-empty and unique")
    if (
        not mapping.get("weight")
        or not (mapping.get("identifier") or mapping.get("name"))
        or set(mapping)
        - {"identifier", "name", "weight", "asset_type", "exchange", "cusip", "isin"}
        or any(v not in headers for v in mapping.values())
    ):
        raise InvalidCsv("Map weight and identifier/name to exact source headers")
    if weight_unit not in {"percent", "decimal"}:
        raise InvalidCsv("Confirm percent or decimal weight units")
    rows = []
    for source in records[header_index + 1 :]:
        if not any(v.strip().replace("\xa0", "") for v in source):
            if format_id != "manual":
                break  # official table terminates before legal footnotes
            continue
        if len(source) != len(headers) or any(len(v) > 2000 for v in source):
            raise InvalidCsv("Malformed/oversized holdings row or changed trailer")
        row = dict(zip(headers, source, strict=True))
        if format_id == "spdr":
            row["__class"] = (
                "cash"
                if row.get("Ticker") in {"USD", "CASH"}
                else "equity"
                if row.get("Identifier", "") not in {"", "-"}
                else "other"
            )
        rows.append(row)
        if len(rows) > max_rows:
            raise InvalidCsv("Holdings exceed configured row limit")
    if not rows:
        raise InvalidCsv("No holdings rows found")
    return ParsedFund(
        as_of, f"{format_id}-fund/1", source_url, rows, mapping, weight_unit
    )
