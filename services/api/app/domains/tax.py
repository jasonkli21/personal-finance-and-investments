"""Reviewed source-backed tax-lot import, audit, and read operations."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from collections import defaultdict
from datetime import UTC, date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.api.stage3_contracts import (
    TaxLotAdjustmentCreate,
    TaxLotImportCorrection,
    TaxLotImportPublish,
)
from app.db.models import (
    Account,
    PrivateFile,
    Security,
    TaxLot,
    TaxLotAdjustment,
    TaxLotImport,
    TaxLotImportRow,
    TaxLotReviewEvent,
    utc_now,
)
from app.domains import portfolio
from app.storage.file_store import PrivateFileStore

TAX_LOT_PARSER_VERSION = "tax-lots-csv-v1"
MAX_TAX_LOT_ROWS = 500
DECIMAL_PATTERN = re.compile(r"^-?\d{1,18}(?:\.\d{1,10})?$")


class TaxError(ValueError):
    """Tax lot operation failed validation, review, or concurrency checks."""


def _filename(value: str) -> str:
    basename = Path(value.replace("\\", "/")).name
    clean = "".join(char for char in basename if char >= " " and char != "\x7f")
    clean = clean.strip()[:200]
    if not clean.casefold().endswith(".csv"):
        raise TaxError("Upload a tax-lot CSV file.")
    return clean


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    raw = value.strip().replace("$", "").replace(",", "").replace(" ", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    if not DECIMAL_PATTERN.fullmatch(raw):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _parse_date(value: str | None) -> date | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return date.fromisoformat(raw)
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", raw):
            month, day, year = (int(part) for part in raw.split("/"))
            return date(year, month, day)
    except ValueError:
        return None
    return None


def _identity_key(
    *,
    account_id: UUID,
    source_label: str,
    security_id: UUID,
    source_lot_id: str | None,
    acquired_at: date | None,
    initial_quantity: Decimal | None,
    remaining_quantity: Decimal,
    remaining_basis: Decimal | None,
    basis_currency: str | None,
) -> str:
    fields: tuple[str, ...]
    if source_lot_id:
        fields = (
            str(account_id),
            source_label,
            str(security_id),
            source_lot_id.strip(),
        )
    else:
        fields = (
            str(account_id),
            source_label,
            str(security_id),
            acquired_at.isoformat() if acquired_at else "",
            str(initial_quantity) if initial_quantity is not None else "",
            str(remaining_quantity),
            str(remaining_basis) if remaining_basis is not None else "",
            basis_currency or "",
        )
    return hashlib.sha256("\0".join(fields).encode()).hexdigest()


def _private_file(
    session: Session, *, digest: str, key: str, filename: str, byte_size: int
) -> PrivateFile:
    existing = session.scalar(
        select(PrivateFile).where(PrivateFile.content_hash == digest)
    )
    if existing is not None:
        if existing.content_type not in {"text/csv", "application/csv"}:
            raise TaxError("This content hash has a conflicting file media type.")
        return existing
    row = PrivateFile(
        id=uuid4(),
        content_hash=digest,
        storage_key=key,
        original_name=filename,
        content_type="text/csv",
        byte_size=byte_size,
    )
    session.add(row)
    session.flush()
    return row


def create_csv_import(
    session_factory: sessionmaker[Session],
    file_store: PrivateFileStore,
    *,
    content: bytes,
    filename: str,
    account_id: UUID,
    source_label: str,
    idempotency_key: str,
    mapping: dict[str, str],
    max_file_bytes: int = 5_000_000,
) -> tuple[UUID, bool]:
    safe_name = _filename(filename)
    label = source_label.strip()
    if not 1 <= len(label) <= 100:
        raise TaxError("Source label must contain 1 to 100 characters.")
    if not 1 <= len(idempotency_key) <= 128:
        raise TaxError("A valid idempotency key is required.")
    if not content or len(content) > max_file_bytes:
        raise TaxError("CSV is empty or exceeds the configured size limit.")
    if "ticker" not in mapping or "remaining_quantity" not in mapping:
        raise TaxError("Map at least ticker and remaining_quantity columns.")
    if any(not isinstance(value, str) or not value for value in mapping.values()):
        raise TaxError("Every mapped source column must be selected.")
    if not set(mapping).issubset(
        {
            "ticker",
            "source_lot_id",
            "acquired_at",
            "initial_quantity",
            "remaining_quantity",
            "initial_basis",
            "remaining_basis",
            "basis_currency",
            "evidence_ref",
        }
    ):
        raise TaxError("The column mapping contains an unsupported field.")

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TaxError("CSV must be UTF-8 encoded.") from exc
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    headers = reader.fieldnames
    if not headers or any(not header.strip() for header in headers):
        raise TaxError("CSV needs non-empty column headers.")
    if len(set(headers)) != len(headers):
        raise TaxError("CSV headers must be unique.")
    if any(header not in headers for header in mapping.values()):
        raise TaxError("A selected source column is missing.")

    parsed: list[dict[str, Any]] = []
    for row_number, raw in enumerate(reader, start=1):
        if row_number > MAX_TAX_LOT_ROWS:
            raise TaxError(f"Tax-lot CSV contains more than {MAX_TAX_LOT_ROWS} rows.")
        extra = raw.pop(None, [])
        raw_values: dict[str, Any] = {
            str(key): str(value or "") for key, value in raw.items()
        }
        if extra:
            raw_values["__extra_fields__"] = [str(item or "") for item in extra]
        values = {
            field: raw_values.get(header, "").strip()
            for field, header in mapping.items()
        }
        diagnostics: dict[str, Any] = {}
        row_status = "ready"
        ticker = values.get("ticker", "").strip()
        if not ticker:
            row_status = "needs_review"
            diagnostics["ticker"] = "missing"
        elif len(ticker) > 200:
            row_status = "needs_review"
            diagnostics["ticker"] = "too_long"
        remaining_quantity = _parse_decimal(values.get("remaining_quantity"))
        if remaining_quantity is None or remaining_quantity <= 0:
            row_status = "needs_review"
            diagnostics["remaining_quantity"] = "missing_or_invalid_positive_quantity"
        initial_quantity = _parse_decimal(values.get("initial_quantity"))
        if values.get("initial_quantity") and initial_quantity is None:
            row_status = "needs_review"
            diagnostics["initial_quantity"] = "invalid"
        if (
            remaining_quantity is not None
            and initial_quantity is not None
            and initial_quantity < remaining_quantity
        ):
            row_status = "needs_review"
            diagnostics["initial_quantity"] = "less_than_remaining_quantity"

        acquired_text = values.get("acquired_at")
        acquired_at = _parse_date(acquired_text)
        if acquired_text and acquired_at is None:
            row_status = "needs_review"
            diagnostics["acquired_at"] = "invalid_date"
        elif acquired_at is not None and acquired_at > date.today():
            row_status = "needs_review"
            diagnostics["acquired_at"] = "future_date"
        elif not acquired_at:
            diagnostics["acquired_at"] = "missing_unavailable"

        initial_basis = _parse_decimal(values.get("initial_basis"))
        if values.get("initial_basis") and (initial_basis is None or initial_basis < 0):
            row_status = "needs_review"
            diagnostics["initial_basis"] = "invalid_nonnegative_amount"
        remaining_basis = _parse_decimal(values.get("remaining_basis"))
        if values.get("remaining_basis") and (
            remaining_basis is None or remaining_basis < 0
        ):
            row_status = "needs_review"
            diagnostics["remaining_basis"] = "invalid_nonnegative_amount"
        elif remaining_basis is None:
            diagnostics["remaining_basis"] = "missing_unavailable"

        currency_raw = values.get("basis_currency", "").upper()
        basis_currency = currency_raw or None
        if currency_raw and not re.fullmatch(r"[A-Z]{3}", currency_raw):
            row_status = "needs_review"
            diagnostics["basis_currency"] = "invalid_currency"
            basis_currency = None
        elif (
            initial_basis is not None or remaining_basis is not None
        ) and basis_currency is None:
            row_status = "needs_review"
            diagnostics["basis_currency"] = "missing_unavailable"

        source_lot_id = values.get("source_lot_id") or None
        if source_lot_id is not None and len(source_lot_id) > 200:
            row_status = "needs_review"
            diagnostics["source_lot_id"] = "too_long"
            source_lot_id = None
        evidence_ref = values.get("evidence_ref") or None
        if evidence_ref is not None and len(evidence_ref) > 500:
            row_status = "needs_review"
            diagnostics["evidence_ref"] = "too_long"
            evidence_ref = None

        quality_status = (
            "reported"
            if acquired_at is not None
            and initial_quantity is not None
            and remaining_basis is not None
            and basis_currency is not None
            else "incomplete"
        )
        parsed.append(
            {
                "row_number": row_number,
                "raw_payload": raw_values,
                "raw_ticker": ticker or None if len(ticker) <= 200 else None,
                "raw_source_lot_id": source_lot_id,
                "acquired_at": acquired_at,
                "initial_quantity": initial_quantity,
                "remaining_quantity": remaining_quantity,
                "initial_basis": initial_basis,
                "remaining_basis": remaining_basis,
                "basis_currency": basis_currency,
                "evidence_ref": evidence_ref,
                "quality_status": quality_status,
                "row_status": row_status,
                "diagnostics": diagnostics,
            }
        )
    if not parsed:
        raise TaxError("CSV contains no lot rows.")

    with session_factory() as session:
        account = session.get(Account, account_id)
        if account is None or not account.active:
            raise TaxError("Active account not found.")
        tickers = {
            row["raw_ticker"].casefold()
            for row in parsed
            if row["raw_ticker"] is not None
        }
        securities = list(
            session.scalars(
                select(Security).where(func.lower(Security.display_ticker).in_(tickers))
            )
        )
        by_ticker: dict[str, list[Security]] = defaultdict(list)
        for security in securities:
            if security.display_ticker:
                by_ticker[security.display_ticker.casefold()].append(security)
        for row in parsed:
            ticker = row["raw_ticker"]
            matches = by_ticker.get(ticker.casefold(), []) if ticker else []
            if len(matches) == 1:
                security = matches[0]
                row["security_id"] = security.id
                if security.security_type not in {"equity", "etf"}:
                    row["row_status"] = "needs_review"
                    row["diagnostics"]["security_type"] = "unsupported_for_tax_lots"
            else:
                row["security_id"] = None
                row["row_status"] = "needs_review"
                if row["diagnostics"].get("ticker") != "too_long":
                    row["diagnostics"]["ticker"] = (
                        "unknown" if not matches else "ambiguous"
                    )

    file_key, digest = file_store.put(content)
    now = utc_now()

    def persist(session: Session) -> tuple[UUID, bool]:
        previous_key = session.scalar(
            select(TaxLotImport).where(TaxLotImport.idempotency_key == idempotency_key)
        )
        if previous_key is not None:
            if (
                previous_key.account_id != account_id
                or previous_key.source_label != label
                or previous_key.file_sha256 != digest
            ):
                raise TaxError("Idempotency key was used for a different import.")
            return previous_key.id, True
        existing_import = session.scalar(
            select(TaxLotImport).where(
                TaxLotImport.account_id == account_id,
                TaxLotImport.source_label == label,
                TaxLotImport.file_sha256 == digest,
            )
        )
        if existing_import is not None:
            return existing_import.id, True
        private_file = _private_file(
            session,
            digest=digest,
            key=file_key,
            filename=safe_name,
            byte_size=len(content),
        )
        record = TaxLotImport(
            id=uuid4(),
            account_id=account_id,
            file_id=private_file.id,
            source_label=label,
            parser_version=TAX_LOT_PARSER_VERSION,
            file_sha256=digest,
            idempotency_key=idempotency_key,
            review_revision=1,
            row_count=len(parsed),
            status="review",
            diagnostics={"mapping": mapping, "row_count": len(parsed)},
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        seen_keys: dict[str, int] = {}
        for row in parsed:
            identity_key = None
            if row["security_id"] is not None and row["remaining_quantity"] is not None:
                identity_key = _identity_key(
                    account_id=account_id,
                    source_label=label,
                    security_id=row["security_id"],
                    source_lot_id=row["raw_source_lot_id"],
                    acquired_at=row["acquired_at"],
                    initial_quantity=row["initial_quantity"],
                    remaining_quantity=row["remaining_quantity"],
                    remaining_basis=row["remaining_basis"],
                    basis_currency=row["basis_currency"],
                )
                prior_row = seen_keys.get(identity_key)
                existing_lot = session.scalar(
                    select(TaxLot).where(
                        TaxLot.account_id == account_id,
                        TaxLot.source_label == label,
                        TaxLot.identity_key == identity_key,
                    )
                )
                if prior_row is not None:
                    row["row_status"] = "duplicate"
                    row["diagnostics"]["duplicate_source_row"] = prior_row
                elif existing_lot is not None:
                    row["row_status"] = "duplicate"
                    row["diagnostics"]["duplicate_tax_lot_id"] = str(existing_lot.id)
                else:
                    seen_keys[identity_key] = row["row_number"]
                row["diagnostics"]["identity_key"] = identity_key
            session.add(
                TaxLotImportRow(
                    id=uuid4(),
                    import_id=record.id,
                    row_number=row["row_number"],
                    raw_payload=row["raw_payload"],
                    raw_ticker=row["raw_ticker"],
                    raw_source_lot_id=row["raw_source_lot_id"],
                    security_id=row["security_id"],
                    acquired_at=row["acquired_at"],
                    initial_quantity=row["initial_quantity"],
                    remaining_quantity=row["remaining_quantity"],
                    initial_basis=row["initial_basis"],
                    remaining_basis=row["remaining_basis"],
                    basis_currency=row["basis_currency"],
                    evidence_ref=row["evidence_ref"],
                    quality_status=row["quality_status"],
                    row_status=row["row_status"],
                    diagnostics=row["diagnostics"],
                    created_at=now,
                    updated_at=now,
                )
            )
        session.flush()
        return record.id, False

    from app.db.transactions import run_database_unit

    return run_database_unit(session_factory, persist)


def _adjustments(
    session: Session, lot_ids: list[UUID]
) -> dict[UUID, list[TaxLotAdjustment]]:
    result: dict[UUID, list[TaxLotAdjustment]] = defaultdict(list)
    if lot_ids:
        rows = list(
            session.scalars(
                select(TaxLotAdjustment)
                .where(TaxLotAdjustment.tax_lot_id.in_(lot_ids))
                .order_by(TaxLotAdjustment.effective_date, TaxLotAdjustment.created_at)
                .limit(10_001)
            )
        )
        if len(rows) > 10_000:
            raise TaxError(
                "Lot adjustment history exceeds the 10,000-row review limit."
            )
        for row in rows:
            result[row.tax_lot_id].append(row)
    return result


def lot_state(
    lot: TaxLot, adjustments: list[TaxLotAdjustment]
) -> tuple[Decimal, Decimal | None]:
    with localcontext() as context:
        context.prec = 80
        quantity = lot.remaining_quantity + sum(
            (row.quantity_delta or Decimal(0) for row in adjustments), Decimal(0)
        )
        basis = None
        if lot.remaining_basis is not None:
            basis = lot.remaining_basis + sum(
                (row.basis_delta or Decimal(0) for row in adjustments), Decimal(0)
            )
        return quantity, basis


def _adjustments_keep_nonnegative(
    quantity: Decimal,
    basis: Decimal | None,
    adjustments: list[TaxLotAdjustment],
) -> bool:
    with localcontext() as context:
        context.prec = 80
        current_quantity = quantity
        current_basis = basis
        for adjustment in adjustments:
            current_quantity += adjustment.quantity_delta or Decimal(0)
            if current_quantity < 0:
                return False
            if current_basis is not None:
                current_basis += adjustment.basis_delta or Decimal(0)
                if current_basis < 0:
                    return False
        return True


def _quantity_reconciliation(
    session: Session, record: TaxLotImport, rows: list[TaxLotImportRow]
) -> tuple[list[dict[str, Any]], list[str]]:
    gaps: list[str] = []
    owned = portfolio.read_positions(session, record.account_id)
    position_quantities: dict[UUID, Decimal] = {}
    if owned.snapshot is None:
        gaps.append(
            "No selected accepted position snapshot is available for reconciliation."
        )
        snapshot_id = None
    else:
        snapshot_id = owned.snapshot.id
        for position in owned.snapshot.positions:
            position_quantities[position.security.id] = Decimal(position.quantity)

    existing_lots = list(
        session.scalars(
            select(TaxLot).where(TaxLot.account_id == record.account_id).limit(1001)
        )
    )
    if len(existing_lots) > 1000:
        gaps.append("Lot reconciliation is capped at 1,000 existing lots.")
        existing_lots = existing_lots[:1000]
    adjustments = _adjustments(session, [lot.id for lot in existing_lots])
    lot_quantities: dict[UUID, Decimal] = defaultdict(Decimal)
    for lot in existing_lots:
        quantity, _basis = lot_state(lot, adjustments.get(lot.id, []))
        lot_quantities[lot.security_id] += quantity

    for row in rows:
        if row.row_status == "needs_review":
            gaps.append(f"Row {row.row_number} needs review before publication.")
        if row.row_status == "ready" and row.security_id and row.remaining_quantity:
            lot_quantities[row.security_id] += row.remaining_quantity
    if snapshot_id is None:
        return [], gaps
    differences: list[dict[str, Any]] = []
    securities = list(
        session.scalars(
            select(Security).where(
                Security.id.in_(set(position_quantities) | set(lot_quantities))
            )
        )
    )
    by_id = {security.id: security for security in securities}
    for security_id in sorted(set(position_quantities) | set(lot_quantities), key=str):
        position_quantity = position_quantities.get(security_id, Decimal(0))
        lot_quantity = lot_quantities.get(security_id, Decimal(0))
        difference = lot_quantity - position_quantity
        differences.append(
            {
                "security_id": security_id,
                "ticker": by_id[security_id].display_ticker
                if security_id in by_id
                else None,
                "position_quantity": str(position_quantity),
                "lot_quantity": str(lot_quantity),
                "difference": str(difference),
            }
        )
    return differences, gaps


def read_import(session: Session, import_id: UUID) -> dict[str, Any]:
    record = session.get(TaxLotImport, import_id)
    if record is None:
        raise TaxError("Tax-lot import not found.")
    rows = list(
        session.scalars(
            select(TaxLotImportRow)
            .where(TaxLotImportRow.import_id == import_id)
            .order_by(TaxLotImportRow.row_number)
        )
    )
    differences, gaps = _quantity_reconciliation(session, record, rows)
    lot_by_import_row = {
        lot.import_row_id: lot.id
        for lot in session.scalars(
            select(TaxLot).where(TaxLot.import_id == import_id).limit(1000)
        )
    }
    security_ids = {row.security_id for row in rows if row.security_id is not None}
    securities = {
        item.id: item
        for item in session.scalars(
            select(Security).where(Security.id.in_(security_ids))
        )
    }
    return {
        "id": record.id,
        "account_id": record.account_id,
        "source_label": record.source_label,
        "file_sha256": record.file_sha256,
        "status": record.status,
        "review_revision": record.review_revision,
        "row_count": record.row_count,
        "diagnostics": record.diagnostics,
        "rows": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "raw_payload": row.raw_payload,
                "raw_ticker": row.raw_ticker,
                "raw_source_lot_id": row.raw_source_lot_id,
                "security_id": row.security_id,
                "ticker": (
                    securities[row.security_id].display_ticker
                    if row.security_id in securities
                    else None
                ),
                "acquired_at": row.acquired_at,
                "initial_quantity": _text(row.initial_quantity),
                "remaining_quantity": _text(row.remaining_quantity),
                "initial_basis": _text(row.initial_basis),
                "remaining_basis": _text(row.remaining_basis),
                "basis_currency": row.basis_currency,
                "evidence_ref": row.evidence_ref,
                "quality_status": row.quality_status,
                "row_status": row.row_status,
                "diagnostics": row.diagnostics,
                "tax_lot_id": lot_by_import_row.get(row.id),
            }
            for row in rows
        ],
        "quantity_differences": differences,
        "gaps": gaps,
    }


def _text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def correct_import_row(
    session: Session,
    import_id: UUID,
    row_id: UUID,
    data: TaxLotImportCorrection,
) -> TaxLotImportRow:
    record = session.get(TaxLotImport, import_id)
    if record is None:
        raise TaxError("Tax-lot import not found.")
    if record.status != "review":
        raise TaxError("Only an unpublished import can be corrected.")
    if record.review_revision != data.expected_revision:
        raise TaxError("Tax-lot review revision changed; reload before correcting.")
    claimed_revision = data.expected_revision + 1
    claim = cast(
        Any,
        session.execute(
            update(TaxLotImport)
            .where(
                TaxLotImport.id == import_id,
                TaxLotImport.status == "review",
                TaxLotImport.review_revision == data.expected_revision,
            )
            .values(review_revision=claimed_revision, updated_at=utc_now())
            .execution_options(synchronize_session=False)
        ),
    )
    if claim.rowcount != 1:
        raise TaxError("Tax-lot review revision changed; reload before correcting.")
    row = session.scalar(
        select(TaxLotImportRow).where(
            TaxLotImportRow.id == row_id, TaxLotImportRow.import_id == import_id
        )
    )
    if row is None:
        raise TaxError("Tax-lot import row not found.")
    if row.row_status == "duplicate":
        raise TaxError("Duplicate rows cannot be converted into another lot.")
    changes: dict[str, Any] = {}
    for field in (
        "security_id",
        "source_lot_id",
        "acquired_at",
        "initial_quantity",
        "remaining_quantity",
        "initial_basis",
        "remaining_basis",
        "basis_currency",
        "evidence_ref",
    ):
        if field not in data.model_fields_set:
            continue
        value = getattr(data, field)
        attribute = "raw_source_lot_id" if field == "source_lot_id" else field
        if field == "source_lot_id":
            value = value.strip() or None if value is not None else None
        if field in {
            "initial_quantity",
            "remaining_quantity",
            "initial_basis",
            "remaining_basis",
        }:
            value = Decimal(value) if value is not None else None
        changes[field] = value
        setattr(row, attribute, value)

    diagnostics = dict(row.diagnostics)
    for key in (
        "ticker",
        "source_lot_id",
        "evidence_ref",
        "security_type",
        "remaining_quantity",
        "initial_quantity",
        "acquired_at",
        "initial_basis",
        "remaining_basis",
        "basis_currency",
    ):
        diagnostics.pop(key, None)
    status = "ready"
    if row.security_id is None:
        status = "needs_review"
        diagnostics["ticker"] = "unresolved"
    security = session.get(Security, row.security_id) if row.security_id else None
    if row.security_id is not None and security is None:
        status = "needs_review"
        diagnostics["ticker"] = "security_not_found"
    if security is not None and security.security_type not in {"equity", "etf"}:
        status = "needs_review"
        diagnostics["security_type"] = "unsupported_for_tax_lots"
    if row.remaining_quantity is None or row.remaining_quantity <= 0:
        status = "needs_review"
        diagnostics["remaining_quantity"] = "missing_or_invalid_positive_quantity"
    if (
        row.initial_quantity is not None
        and row.remaining_quantity is not None
        and row.initial_quantity < row.remaining_quantity
    ):
        status = "needs_review"
        diagnostics["initial_quantity"] = "less_than_remaining_quantity"
    if row.acquired_at and row.acquired_at > date.today():
        status = "needs_review"
        diagnostics["acquired_at"] = "future_date"
    if row.remaining_basis is not None and row.remaining_basis < 0:
        status = "needs_review"
        diagnostics["remaining_basis"] = "negative_basis"
    if row.initial_basis is not None and row.initial_basis < 0:
        status = "needs_review"
        diagnostics["initial_basis"] = "negative_basis"
    if (
        row.initial_basis is not None or row.remaining_basis is not None
    ) and row.basis_currency is None:
        status = "needs_review"
        diagnostics["basis_currency"] = "missing_unavailable"
    row.quality_status = (
        "reported"
        if row.acquired_at is not None
        and row.initial_quantity is not None
        and row.remaining_basis is not None
        and row.basis_currency is not None
        else "incomplete"
    )
    if status == "ready" and row.security_id and row.remaining_quantity:
        identity_key = _identity_key(
            account_id=record.account_id,
            source_label=record.source_label,
            security_id=row.security_id,
            source_lot_id=row.raw_source_lot_id,
            acquired_at=row.acquired_at,
            initial_quantity=row.initial_quantity,
            remaining_quantity=row.remaining_quantity,
            remaining_basis=row.remaining_basis,
            basis_currency=row.basis_currency,
        )
        existing_lot = session.scalar(
            select(TaxLot).where(
                TaxLot.account_id == record.account_id,
                TaxLot.source_label == record.source_label,
                TaxLot.identity_key == identity_key,
            )
        )
        if existing_lot is not None:
            status = "duplicate"
            diagnostics["duplicate_tax_lot_id"] = str(existing_lot.id)
        else:
            other_rows = session.scalars(
                select(TaxLotImportRow)
                .where(
                    TaxLotImportRow.import_id == record.id,
                    TaxLotImportRow.id != row.id,
                    TaxLotImportRow.row_status == "ready",
                )
                .limit(MAX_TAX_LOT_ROWS)
            )
            for other in other_rows:
                if other.security_id is None or other.remaining_quantity is None:
                    continue
                other_key = _identity_key(
                    account_id=record.account_id,
                    source_label=record.source_label,
                    security_id=other.security_id,
                    source_lot_id=other.raw_source_lot_id,
                    acquired_at=other.acquired_at,
                    initial_quantity=other.initial_quantity,
                    remaining_quantity=other.remaining_quantity,
                    remaining_basis=other.remaining_basis,
                    basis_currency=other.basis_currency,
                )
                if other_key == identity_key:
                    status = "duplicate"
                    diagnostics["duplicate_source_row"] = other.row_number
                    break
    row.row_status = status
    row.diagnostics = diagnostics
    record.review_revision = claimed_revision
    record.updated_at = utc_now()
    session.add(
        TaxLotReviewEvent(
            id=uuid4(),
            import_id=record.id,
            import_row_id=row.id,
            review_revision=record.review_revision,
            action="correct_row",
            reason=data.reason,
            change_payload=json.loads(json.dumps(changes, default=str)),
        )
    )
    session.flush()
    return row


def publish_import(
    session: Session,
    import_id: UUID,
    data: TaxLotImportPublish,
) -> TaxLotImport:
    record = session.get(TaxLotImport, import_id)
    if record is None:
        raise TaxError("Tax-lot import not found.")
    if record.status == "published":
        return record
    if record.status != "review":
        raise TaxError("Tax-lot import is not awaiting publication.")
    if record.review_revision != data.expected_revision:
        raise TaxError("Tax-lot review revision changed; reload before publication.")
    rows = list(
        session.scalars(
            select(TaxLotImportRow)
            .where(TaxLotImportRow.import_id == import_id)
            .order_by(TaxLotImportRow.row_number)
        )
    )
    try:
        publication_limit = int(
            os.environ.get("TAX_LOT_PUBLICATION_MAX_ROWS", str(MAX_TAX_LOT_ROWS))
        )
    except ValueError as exc:
        raise TaxError("Tax-lot publication batch limit is invalid.") from exc
    if not 1 <= publication_limit <= MAX_TAX_LOT_ROWS:
        raise TaxError("Tax-lot publication batch limit must be between 1 and 500.")
    if len(rows) > publication_limit:
        raise TaxError(
            f"This import has {len(rows)} rows, above the configured safe "
            f"publication limit of {publication_limit}."
        )
    published_keys = set(
        session.scalars(
            select(TaxLot.identity_key).where(
                TaxLot.account_id == record.account_id,
                TaxLot.source_label == record.source_label,
            )
        )
    )
    seen_keys = set(published_keys)
    for row in rows:
        if (
            row.row_status != "ready"
            or row.security_id is None
            or row.remaining_quantity is None
        ):
            continue
        identity_key = _identity_key(
            account_id=record.account_id,
            source_label=record.source_label,
            security_id=row.security_id,
            source_lot_id=row.raw_source_lot_id,
            acquired_at=row.acquired_at,
            initial_quantity=row.initial_quantity,
            remaining_quantity=row.remaining_quantity,
            remaining_basis=row.remaining_basis,
            basis_currency=row.basis_currency,
        )
        if identity_key in seen_keys:
            row.row_status = "duplicate"
            row.diagnostics = {
                **row.diagnostics,
                "duplicate_source_identity": True,
            }
        else:
            seen_keys.add(identity_key)
    if any(row.row_status == "needs_review" for row in rows):
        raise TaxError("Correct or explicitly resolve every blocking row first.")
    differences, gaps = _quantity_reconciliation(session, record, rows)
    mismatches = [row for row in differences if Decimal(row["difference"]) != 0]
    if (mismatches or gaps) and not data.acknowledge_quantity_differences:
        raise TaxError(
            "Review and acknowledge lot-to-position differences and coverage gaps "
            "before publication."
        )
    claimed = cast(
        Any,
        session.execute(
            update(TaxLotImport)
            .where(
                TaxLotImport.id == import_id,
                TaxLotImport.status == "review",
                TaxLotImport.review_revision == data.expected_revision,
            )
            .values(status="published", published_at=utc_now(), updated_at=utc_now())
            .execution_options(synchronize_session=False)
        ),
    )
    if claimed.rowcount != 1:
        raise TaxError("Tax-lot review revision changed; reload before publication.")
    existing_keys = set(
        session.scalars(
            select(TaxLot.identity_key).where(
                TaxLot.account_id == record.account_id,
                TaxLot.source_label == record.source_label,
            )
        )
    )
    for row in rows:
        if row.row_status != "ready":
            continue
        if row.security_id is None or row.remaining_quantity is None:
            raise TaxError(
                f"Row {row.row_number} is missing a required security or quantity."
            )
        identity_key = _identity_key(
            account_id=record.account_id,
            source_label=record.source_label,
            security_id=row.security_id,
            source_lot_id=row.raw_source_lot_id,
            acquired_at=row.acquired_at,
            initial_quantity=row.initial_quantity,
            remaining_quantity=row.remaining_quantity,
            remaining_basis=row.remaining_basis,
            basis_currency=row.basis_currency,
        )
        if identity_key in existing_keys:
            row.row_status = "duplicate"
            row.diagnostics = {
                **row.diagnostics,
                "duplicate_source_identity": True,
            }
            continue
        session.add(
            TaxLot(
                id=uuid4(),
                account_id=record.account_id,
                security_id=row.security_id,
                import_id=record.id,
                import_row_id=row.id,
                source_label=record.source_label,
                source_lot_id=row.raw_source_lot_id,
                identity_key=identity_key,
                acquired_at=row.acquired_at,
                initial_quantity=row.initial_quantity,
                remaining_quantity=row.remaining_quantity,
                initial_basis=row.initial_basis,
                remaining_basis=row.remaining_basis,
                basis_currency=row.basis_currency,
                evidence_ref=row.evidence_ref,
                quality_status=row.quality_status,
            )
        )
        row.row_status = "published"
        existing_keys.add(identity_key)
    record.status = "published"
    record.published_at = record.published_at or utc_now()
    record.updated_at = record.published_at
    session.add(
        TaxLotReviewEvent(
            id=uuid4(),
            import_id=record.id,
            import_row_id=None,
            review_revision=record.review_revision,
            action="publish",
            reason=data.reason,
            change_payload=json.loads(
                json.dumps(
                    {
                        "quantity_differences": differences,
                        "gaps": gaps,
                        "acknowledged": data.acknowledge_quantity_differences,
                    },
                    default=str,
                )
            ),
        )
    )
    session.flush()
    return record


def list_lots(
    session: Session,
    *,
    account_id: UUID | None = None,
    security_id: UUID | None = None,
    quality_status: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    statement = select(TaxLot).order_by(
        TaxLot.account_id, TaxLot.security_id, TaxLot.acquired_at, TaxLot.id
    )
    if account_id is not None:
        statement = statement.where(TaxLot.account_id == account_id)
    if security_id is not None:
        statement = statement.where(TaxLot.security_id == security_id)
    if quality_status is not None:
        statement = statement.where(TaxLot.quality_status == quality_status)
    lots = list(session.scalars(statement.limit(limit + 1)))
    if len(lots) > limit:
        raise TaxError("Narrow lot filters; at most 500 lots are returned.")
    securities = {
        row.id: row
        for row in session.scalars(
            select(Security).where(Security.id.in_({lot.security_id for lot in lots}))
        )
    }
    adjustments = _adjustments(session, [lot.id for lot in lots])
    result: list[dict[str, Any]] = []
    for lot in lots:
        current_quantity, current_basis = lot_state(lot, adjustments.get(lot.id, []))
        security = securities[lot.security_id]
        result.append(
            {
                "id": lot.id,
                "account_id": lot.account_id,
                "security_id": lot.security_id,
                "ticker": security.display_ticker,
                "security_name": security.name,
                "import_id": lot.import_id,
                "source_label": lot.source_label,
                "source_lot_id": lot.source_lot_id,
                "acquired_at": lot.acquired_at,
                "initial_quantity": str(lot.initial_quantity)
                if lot.initial_quantity is not None
                else None,
                "remaining_quantity": str(lot.remaining_quantity),
                "current_remaining_quantity": str(current_quantity),
                "initial_basis": _text(lot.initial_basis),
                "remaining_basis": _text(lot.remaining_basis),
                "current_remaining_basis": _text(current_basis),
                "basis_currency": lot.basis_currency,
                "evidence_ref": lot.evidence_ref,
                "quality_status": lot.quality_status,
                "adjustments": [
                    {
                        "id": item.id,
                        "tax_lot_id": item.tax_lot_id,
                        "adjustment_type": item.adjustment_type,
                        "quantity_delta": _text(item.quantity_delta),
                        "basis_delta": _text(item.basis_delta),
                        "basis_currency": item.basis_currency,
                        "effective_date": item.effective_date,
                        "source_label": item.source_label,
                        "reason": item.reason,
                        "evidence_ref": item.evidence_ref,
                        "created_at": item.created_at,
                    }
                    for item in adjustments.get(lot.id, [])
                ],
            }
        )
    return result


def create_adjustment(
    session: Session,
    lot_id: UUID,
    data: TaxLotAdjustmentCreate,
) -> TaxLotAdjustment:
    lot = session.get(TaxLot, lot_id)
    if lot is None:
        raise TaxError("Tax lot not found.")
    if data.effective_date > date.today():
        raise TaxError("Lot adjustments cannot be dated in the future.")
    quantity_delta = (
        Decimal(data.quantity_delta) if data.quantity_delta is not None else None
    )
    basis_delta = Decimal(data.basis_delta) if data.basis_delta is not None else None
    if quantity_delta == 0:
        raise TaxError("Quantity adjustment must be nonzero.")
    if basis_delta == 0:
        raise TaxError("Basis adjustment must be nonzero.")
    if basis_delta is not None:
        if lot.remaining_basis is None or lot.basis_currency is None:
            raise TaxError(
                "A basis adjustment requires source-supplied remaining basis "
                "and currency."
            )
        if data.basis_currency != lot.basis_currency:
            raise TaxError("Adjustment currency must match the lot basis currency.")
    existing = session.scalar(
        select(TaxLotAdjustment).where(
            TaxLotAdjustment.idempotency_key == data.idempotency_key
        )
    )
    if existing is not None:
        same = (
            existing.tax_lot_id == lot_id
            and existing.adjustment_type == data.adjustment_type
            and existing.quantity_delta == quantity_delta
            and existing.basis_delta == basis_delta
            and existing.basis_currency == data.basis_currency
            and existing.effective_date == data.effective_date
            and existing.source_label == data.source_label
            and existing.reason == data.reason
            and existing.evidence_ref == data.evidence_ref
            and existing.raw_values == data.raw_values
        )
        if not same:
            raise TaxError("Idempotency key was used for another lot adjustment.")
        return existing
    prior = list(
        session.scalars(
            select(TaxLotAdjustment)
            .where(TaxLotAdjustment.tax_lot_id == lot_id)
            .order_by(
                TaxLotAdjustment.effective_date,
                TaxLotAdjustment.created_at,
                TaxLotAdjustment.id,
            )
            .limit(10_001)
        )
    )
    if len(prior) > 10_000:
        raise TaxError("Lot adjustment history exceeds the 10,000-row write limit.")
    all_adjustments = [*prior]
    candidate = TaxLotAdjustment(
        id=uuid4(),
        tax_lot_id=lot_id,
        adjustment_type=data.adjustment_type,
        quantity_delta=quantity_delta,
        basis_delta=basis_delta,
        basis_currency=data.basis_currency,
        effective_date=data.effective_date,
        source_label=data.source_label,
        reason=data.reason,
        evidence_ref=data.evidence_ref,
        idempotency_key=data.idempotency_key,
        raw_values=data.raw_values,
    )
    candidate.created_at = utc_now()
    all_adjustments.append(candidate)
    all_adjustments.sort(
        key=lambda row: (
            row.effective_date,
            row.created_at.replace(tzinfo=UTC)
            if row.created_at.tzinfo is None
            else row.created_at.astimezone(UTC),
            row.id,
        )
    )
    if not _adjustments_keep_nonnegative(
        lot.remaining_quantity, lot.remaining_basis, all_adjustments
    ):
        raise TaxError(
            "Adjustment would make the lot quantity or basis negative at an "
            "effective date."
        )
    fence = cast(
        Any,
        session.execute(
            update(TaxLot)
            .where(
                TaxLot.id == lot_id,
                TaxLot.state_revision == lot.state_revision,
            )
            .values(state_revision=TaxLot.state_revision + 1, updated_at=utc_now())
            .execution_options(synchronize_session=False)
        ),
    )
    if fence.rowcount != 1:
        raise TaxError(
            "Tax-lot state revision changed concurrently; retry the adjustment."
        )
    session.add(candidate)
    session.flush()
    return candidate
