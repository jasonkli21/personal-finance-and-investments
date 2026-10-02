"""Bounded, reviewed local CSV position imports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import ImportRowCorrection
from app.db.models import (
    Account,
    ImportAttempt,
    ImportBatch,
    ImportReviewEvent,
    ImportRow,
    Issuer,
    PositionSnapshot,
    PositionSnapshotLine,
    PrivateFile,
    Quote,
    Security,
    SecurityIdentifier,
    utc_now,
)
from app.db.transactions import run_database_unit
from app.storage.file_store import PrivateFileStore

IMPORT_BATCH_ROWS = 200
IMPORT_BATCH_BYTES = 900_000
_DECIMAL = re.compile(r"^-?\d+(?:\.\d{1,10})?$")
_PARSER_VERSION = "positions-csv/1"


class ImportErrorBase(Exception):
    """Base error suitable for a client-safe HTTP response."""


class InvalidCsv(ImportErrorBase):
    """The uploaded content is not a bounded, well-formed CSV."""


class ImportConflict(ImportErrorBase):
    """The same source or idempotency key has a conflicting interpretation."""


class ImportNotFound(ImportErrorBase):
    """The reviewed import or row does not exist."""


class ImportRevisionConflict(ImportErrorBase):
    """The user reviewed a stale import revision."""


class ImportBlocked(ImportErrorBase):
    """One or more source rows need explicit review before publication."""


class ImportAccountConflict(ImportErrorBase):
    """The account head changed after this import was reviewed."""


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal(
    raw: str | None,
    *,
    required: bool,
    nonnegative: bool = False,
    integral_digits: int = 18,
) -> Decimal | None:
    value = (raw or "").strip()
    if not value:
        if required:
            raise ValueError("A numeric value is required")
        return None
    if len(value) > 40 or not _DECIMAL.fullmatch(value):
        raise ValueError("Use a plain decimal with at most 10 fractional places")
    if len(value.lstrip("-").partition(".")[0]) > integral_digits:
        raise ValueError("Numeric value exceeds the supported precision")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not result.is_finite() or (nonnegative and result < 0):
        raise ValueError("Decimal value is outside the supported range")
    return result


def _parse_csv(
    content: bytes, mapping: Mapping[str, str], *, max_rows: int
) -> tuple[list[str], list[dict[str, str]]]:
    if not content or b"\x00" in content:
        raise InvalidCsv("Upload a non-empty UTF-8 CSV file")
    if content[:512].lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise InvalidCsv("The file looks like an HTML page, not a CSV")
    try:
        decoded = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidCsv("CSV files must use UTF-8 encoding") from exc

    try:
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        headers = reader.fieldnames
        if not headers or len(headers) > 100:
            raise InvalidCsv("CSV needs between 1 and 100 header columns")
        normalized = [header.strip() for header in headers]
        if any(not header for header in normalized) or len(set(normalized)) != len(
            normalized
        ):
            raise InvalidCsv("CSV headers must be non-empty and unique")
        headers = normalized
        reader.fieldnames = normalized
        if set(mapping) - {
            "identifier",
            "name",
            "quantity",
            "price",
            "currency",
            "asset_type",
        }:
            raise InvalidCsv("Column mapping contains an unsupported field")
        mapped = {key: value for key, value in mapping.items() if value}
        if "quantity" not in mapped or not ("identifier" in mapped or "name" in mapped):
            raise InvalidCsv(
                "Map quantity and at least one security identifier or name"
            )
        if len(set(mapped.values())) != len(mapped.values()):
            raise InvalidCsv("Each source column can map to only one field")
        if any(column not in headers for column in mapped.values()):
            raise InvalidCsv("Mapped columns must exactly match CSV headers")

        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if row_number - 1 > max_rows:
                raise InvalidCsv(f"CSV exceeds the {max_rows} row limit")
            if None in row or any(value is None for value in row.values()):
                raise InvalidCsv(
                    f"CSV row {row_number} has a different number of columns"
                )
            clean_row = {str(key).strip(): str(value) for key, value in row.items()}
            if any(len(value) > 2000 for value in clean_row.values()):
                raise InvalidCsv(f"CSV row {row_number} contains an oversized field")
            rows.append(clean_row)
    except csv.Error as exc:
        raise InvalidCsv("CSV structure is malformed") from exc
    if not rows:
        raise InvalidCsv("CSV must contain at least one position row")
    return list(headers), rows


def _mapped(
    row: Mapping[str, str], mapping: Mapping[str, str], field: str
) -> str | None:
    column = mapping.get(field)
    value = row.get(column, "") if column else ""
    return value.strip() if value is not None else ""


def _source_filename(filename: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    clean = "".join(char for char in basename if char >= " " and char != "\x7f")
    clean = clean.strip()[:200]
    return clean or "positions.csv"


def _new_file(
    session: Session, *, key: str, digest: str, filename: str, size: int
) -> PrivateFile:
    existing = session.scalar(
        select(PrivateFile).where(PrivateFile.content_hash == digest)
    )
    if existing is not None:
        return existing
    file_row = PrivateFile(
        id=uuid4(),
        content_hash=digest,
        storage_key=key,
        original_name=filename,
        content_type="text/csv",
        byte_size=size,
    )
    session.add(file_row)
    session.flush()
    return file_row


def _match_security(
    session: Session, identifier: str | None, name: str | None
) -> Security | None:
    if identifier:
        normalized = identifier.strip().upper()
        matches = list(
            session.scalars(
                select(Security).where(Security.display_ticker == normalized).limit(2)
            )
        )
        if len(matches) == 1:
            return matches[0]
        identifier_matches = list(
            session.scalars(
                select(Security)
                .join(SecurityIdentifier, SecurityIdentifier.security_id == Security.id)
                .where(
                    SecurityIdentifier.namespace == "ticker",
                    SecurityIdentifier.normalized_value == normalized,
                    SecurityIdentifier.review_status == "reviewed",
                )
                .limit(2)
            )
        )
        if len(identifier_matches) == 1:
            return identifier_matches[0]
    if name:
        matches = list(
            session.scalars(
                select(Security).where(Security.name.ilike(name.strip())).limit(2)
            )
        )
        if len(matches) == 1 and matches[0].name.casefold() == name.strip().casefold():
            return matches[0]
    return None


def _resolve_import_row(
    session: Session,
    *,
    import_id: UUID,
    row_number: int,
    payload: dict[str, str],
    mapping: Mapping[str, str],
    seen: set[UUID],
) -> ImportRow:
    identifier = _mapped(payload, mapping, "identifier")
    name = _mapped(payload, mapping, "name")
    raw_quantity = _mapped(payload, mapping, "quantity")
    raw_price = _mapped(payload, mapping, "price")
    raw_currency = _mapped(payload, mapping, "currency")
    raw_asset_type = _mapped(payload, mapping, "asset_type")
    security = _match_security(session, identifier, name)
    diagnostics: dict[str, str] = {}
    status_value = "ready"
    quantity: Decimal | None = None
    price: Decimal | None = None
    currency = None
    if raw_currency:
        candidate_currency = raw_currency.upper()
        if re.fullmatch(r"[A-Z]{3}", candidate_currency):
            currency = candidate_currency
        else:
            diagnostics["currency"] = "Source currency must be a three-letter code."
            status_value = "invalid"
    try:
        quantity = _decimal(raw_quantity, required=True, integral_digits=18)
    except ValueError as exc:
        diagnostics["quantity"] = str(exc)
        status_value = "invalid"
    try:
        price = _decimal(
            raw_price, required=False, nonnegative=True, integral_digits=14
        )
    except ValueError as exc:
        diagnostics["price"] = str(exc)
        status_value = "invalid"
    if security is None:
        diagnostics["security"] = (
            "No exact local catalog match; choose or create one during review."
        )
        if status_value == "ready":
            status_value = "unmatched"
    elif security.id in seen:
        diagnostics["security"] = (
            "A security may appear only once in a published snapshot."
        )
        status_value = "duplicate"
    else:
        seen.add(security.id)
        currency = currency or (None if raw_currency else security.currency)
        if currency is None:
            diagnostics.setdefault("currency", "A valid currency is required.")
            status_value = "invalid"
        elif currency != security.currency:
            diagnostics["currency"] = "Currency differs from the selected security."
            status_value = "invalid"
    if raw_asset_type and raw_asset_type.casefold() not in {
        "equity",
        "etf",
        "cash",
        "other",
    }:
        diagnostics["asset_type"] = (
            "Unrecognized source asset type is preserved for review."
        )
        if status_value == "ready":
            status_value = "needs_review"

    return ImportRow(
        id=uuid5(import_id, f"row:{row_number}"),
        import_id=import_id,
        row_number=row_number,
        raw_payload=dict(payload),
        raw_identifier=identifier or None,
        raw_name=name or None,
        raw_asset_type=raw_asset_type or None,
        raw_quantity=raw_quantity or None,
        raw_price=raw_price or None,
        raw_currency=raw_currency.upper() if raw_currency else None,
        raw_weight_value=None,
        raw_weight_unit=None,
        security_id=security.id if security else None,
        normalized_quantity=quantity,
        normalized_price=price,
        normalized_weight=None,
        currency=currency,
        row_status=status_value,
        excluded=False,
        diagnostics=diagnostics,
    )


def _batch_rows(rows: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    batches: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    size = 0
    for row in rows:
        row_size = len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        if row_size > IMPORT_BATCH_BYTES:
            raise InvalidCsv("A row exceeds the safe import batch size")
        if current and (
            len(current) >= IMPORT_BATCH_ROWS or size + row_size > IMPORT_BATCH_BYTES
        ):
            batches.append(current)
            current, size = [], 0
        current.append(row)
        size += row_size
    if current:
        batches.append(current)
    return batches


def create_position_import(
    session_factory: sessionmaker[Session],
    file_store: PrivateFileStore,
    *,
    content: bytes,
    filename: str,
    account_id: UUID,
    effective_date: date,
    source_label: str,
    mapping: Mapping[str, str],
    idempotency_key: str,
    expected_account_revision: int,
    max_rows: int,
    replace_existing: bool = False,
) -> tuple[UUID, bool]:
    safe_name = _source_filename(filename)
    if not 1 <= len(idempotency_key) <= 128:
        raise InvalidCsv("A valid idempotency key is required")
    if effective_date > date.today():
        raise InvalidCsv("Position observations cannot be dated in the future.")
    if not 1 <= len(source_label.strip()) <= 100:
        raise InvalidCsv("Source label must contain 1 to 100 characters")
    clean_mapping = {
        key: value.strip() for key, value in mapping.items() if value.strip()
    }
    _headers, parsed_rows = _parse_csv(content, clean_mapping, max_rows=max_rows)
    batches = _batch_rows(parsed_rows)
    file_key, digest = file_store.put(content)
    identity_hash = _canonical_hash(
        ["positions", str(account_id), effective_date.isoformat(), digest]
    )
    interpretation_hash = _canonical_hash([_PARSER_VERSION, clean_mapping])
    payload_hash = _canonical_hash(
        [
            identity_hash,
            interpretation_hash,
            source_label.strip(),
            expected_account_revision,
        ]
    )
    import_id = uuid4()
    filename_clean = safe_name
    now = utc_now()

    def begin_review(session: Session) -> tuple[UUID, bool]:
        existing_key = session.scalar(
            select(ImportAttempt).where(
                ImportAttempt.idempotency_key == idempotency_key
            )
        )
        if existing_key is not None:
            if existing_key.payload_hash != payload_hash:
                raise ImportConflict(
                    "Idempotency key was already used with a different payload."
                )
            return existing_key.id, existing_key.status == "published"

        prior_same = session.scalar(
            select(ImportAttempt)
            .where(
                ImportAttempt.identity_hash == identity_hash,
                ImportAttempt.interpretation_hash == interpretation_hash,
            )
            .order_by(ImportAttempt.created_at)
        )
        if prior_same is not None:
            return prior_same.id, True

        prior_interpretation = session.scalar(
            select(ImportAttempt)
            .where(ImportAttempt.identity_hash == identity_hash)
            .order_by(ImportAttempt.created_at.desc())
        )
        if prior_interpretation is not None and not replace_existing:
            raise ImportConflict(
                "This source was already imported with a different mapping; "
                "mark it as a replacement to continue."
            )
        if prior_interpretation is not None and replace_existing:
            if prior_interpretation.status in {"staging", "review", "blocked"}:
                prior_interpretation.status = "replaced"
                prior_interpretation.updated_at = now

        account = session.get(Account, account_id)
        if account is None or not account.active:
            raise ImportNotFound("Active account not found.")
        if account.current_position_revision != expected_account_revision:
            raise ImportAccountConflict(
                "Account positions changed before import review began."
            )
        private_file = _new_file(
            session,
            key=file_key,
            digest=digest,
            filename=filename_clean,
            size=len(content),
        )
        attempt = ImportAttempt(
            id=import_id,
            file_id=private_file.id,
            kind="positions",
            account_id=account_id,
            fund_security_id=None,
            effective_date=effective_date,
            source_label=source_label.strip(),
            parser_version=_PARSER_VERSION,
            column_mapping=clean_mapping,
            file_sha256=digest,
            identity_hash=identity_hash,
            interpretation_hash=interpretation_hash,
            payload_hash=payload_hash,
            status="staging",
            review_revision=1,
            expected_account_revision=expected_account_revision,
            idempotency_key=idempotency_key,
            row_count=len(parsed_rows),
            batch_count=len(batches),
            diagnostics={"parser": _PARSER_VERSION},
        )
        session.add(attempt)
        session.add(
            ImportReviewEvent(
                id=uuid4(),
                import_id=import_id,
                review_revision=1,
                action="preview",
                reason="CSV parsed and queued for review",
                change_payload={
                    "row_count": len(parsed_rows),
                    "batch_count": len(batches),
                },
                created_at=now,
            )
        )
        return import_id, False

    try:
        created_id, duplicate = run_database_unit(session_factory, begin_review)
    except IntegrityError as exc:
        raise ImportConflict(
            "Import identity conflicted with another in-progress request."
        ) from exc
    if duplicate:
        return created_id, True

    row_offset = 0
    for ordinal, row_batch in enumerate(batches):
        batch_hash = _canonical_hash(row_batch)
        first_row_number = row_offset + 2

        def persist_batch(
            session: Session,
            *,
            batch_ordinal: int,
            staged_hash: str,
            staged_rows: list[dict[str, str]],
            row_number_start: int,
        ) -> None:
            attempt = session.get(ImportAttempt, created_id)
            if attempt is None:
                raise ImportNotFound
            accepted_state = session.execute(
                update(ImportAttempt)
                .where(
                    ImportAttempt.id == created_id,
                    ImportAttempt.status.in_(("staging", "review")),
                    ImportAttempt.review_revision == 1,
                )
                .values(updated_at=utc_now())
                .execution_options(synchronize_session=False)
            )
            if getattr(accepted_state, "rowcount", None) != 1:
                raise ImportConflict(
                    "This import is no longer accepting preview batches."
                )
            marker = session.scalar(
                select(ImportBatch).where(
                    ImportBatch.import_id == created_id,
                    ImportBatch.purpose == "preview",
                    ImportBatch.review_revision == 1,
                    ImportBatch.ordinal == batch_ordinal,
                )
            )
            if marker is not None:
                if marker.payload_hash != staged_hash:
                    raise ImportConflict("Staged preview batch hash changed.")
                return
            seen = {
                security_id
                for security_id in session.scalars(
                    select(ImportRow.security_id).where(
                        ImportRow.import_id == created_id,
                        ImportRow.security_id.is_not(None),
                        ImportRow.row_status.in_(
                            ("ready", "needs_review", "duplicate")
                        ),
                    )
                )
                if security_id is not None
            }
            resolved = [
                _resolve_import_row(
                    session,
                    import_id=created_id,
                    row_number=row_number_start + index,
                    payload=payload,
                    mapping=clean_mapping,
                    seen=seen,
                )
                for index, payload in enumerate(staged_rows)
            ]
            session.add_all(resolved)
            session.add(
                ImportBatch(
                    id=uuid5(created_id, f"preview:{batch_ordinal}"),
                    import_id=created_id,
                    purpose="preview",
                    review_revision=1,
                    ordinal=batch_ordinal,
                    payload_hash=staged_hash,
                    row_count=len(resolved),
                    status="complete",
                )
            )

        run_database_unit(
            session_factory,
            partial(
                persist_batch,
                batch_ordinal=ordinal,
                staged_hash=batch_hash,
                staged_rows=row_batch,
                row_number_start=first_row_number,
            ),
        )
        row_offset += len(row_batch)

    def finish_review(session: Session) -> None:
        updated = session.execute(
            update(ImportAttempt)
            .where(
                ImportAttempt.id == created_id,
                ImportAttempt.status == "staging",
                ImportAttempt.review_revision == 1,
            )
            .values(status="review", updated_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        if getattr(updated, "rowcount", None) != 1:
            with session.no_autoflush:
                if session.get(ImportAttempt, created_id) is None:
                    raise ImportNotFound

    run_database_unit(session_factory, finish_review)
    return created_id, False


def _row_read(session: Session, row: ImportRow) -> dict[str, Any]:
    security = session.get(Security, row.security_id) if row.security_id else None
    return {
        "id": row.id,
        "row_number": row.row_number,
        "raw_payload": row.raw_payload,
        "raw_identifier": row.raw_identifier,
        "raw_name": row.raw_name,
        "raw_asset_type": row.raw_asset_type,
        "raw_quantity": row.raw_quantity,
        "raw_price": row.raw_price,
        "raw_currency": row.raw_currency,
        "security_id": row.security_id,
        "security_label": (security.display_ticker or security.name)
        if security
        else None,
        "normalized_quantity": str(row.normalized_quantity)
        if row.normalized_quantity is not None
        else None,
        "normalized_price": str(row.normalized_price)
        if row.normalized_price is not None
        else None,
        "currency": row.currency,
        "row_status": row.row_status,
        "excluded": row.excluded,
        "correction_reason": row.correction_reason,
        "diagnostics": row.diagnostics,
    }


def read_import(session: Session, import_id: UUID) -> dict[str, Any]:
    attempt = session.get(ImportAttempt, import_id)
    if attempt is None:
        raise ImportNotFound
    rows = list(
        session.scalars(
            select(ImportRow)
            .where(ImportRow.import_id == import_id)
            .order_by(ImportRow.row_number)
        )
    )
    return {
        "id": attempt.id,
        "kind": attempt.kind,
        "account_id": attempt.account_id,
        "effective_date": attempt.effective_date,
        "source_label": attempt.source_label,
        "status": attempt.status,
        "review_revision": attempt.review_revision,
        "row_count": attempt.row_count,
        "expected_account_revision": attempt.expected_account_revision,
        "diagnostics": attempt.diagnostics,
        "rows": [_row_read(session, row) for row in rows],
    }


def correct_import_row(
    session: Session, import_id: UUID, row_id: UUID, correction: ImportRowCorrection
) -> dict[str, Any]:
    attempt = session.get(ImportAttempt, import_id)
    row = session.get(ImportRow, row_id)
    if attempt is None or row is None or row.import_id != import_id:
        raise ImportNotFound
    if attempt.status != "review":
        raise ImportConflict("Only an import under review can be corrected.")
    if attempt.review_revision != correction.expected_review_revision:
        raise ImportRevisionConflict
    new_revision = attempt.review_revision + 1
    now = utc_now()
    advanced = session.execute(
        update(ImportAttempt)
        .where(
            ImportAttempt.id == import_id,
            ImportAttempt.status == "review",
            ImportAttempt.review_revision == correction.expected_review_revision,
        )
        .values(review_revision=new_revision, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if getattr(advanced, "rowcount", None) != 1:
        raise ImportRevisionConflict
    if correction.security_id is not None:
        security = session.get(Security, correction.security_id)
        if security is None:
            raise ImportNotFound("Selected security is not in the local catalog.")
        row.security_id = security.id
        row.currency = correction.currency or row.currency or security.currency
        if row.currency != security.currency:
            raise ImportBlocked("Position currency must match the selected security.")
    if correction.quantity is not None:
        try:
            row.normalized_quantity = _decimal(
                correction.quantity, required=True, integral_digits=18
            )
        except ValueError as exc:
            raise ImportBlocked(str(exc)) from exc
    if correction.price is not None:
        try:
            row.normalized_price = _decimal(
                correction.price,
                required=False,
                nonnegative=True,
                integral_digits=14,
            )
        except ValueError as exc:
            raise ImportBlocked(str(exc)) from exc
    if correction.currency is not None:
        row.currency = correction.currency
    if correction.excluded is not None:
        row.excluded = correction.excluded
    security = session.get(Security, row.security_id) if row.security_id else None
    row.row_status = "excluded" if row.excluded else "ready"
    if not row.excluded and security is None:
        row.row_status = "unmatched"
    if not row.excluded and row.normalized_quantity is None:
        row.row_status = "invalid"
    if security and row.currency != security.currency:
        row.row_status = "invalid"
        row.diagnostics = {
            **row.diagnostics,
            "currency": "Currency differs from selected security.",
        }
    else:
        row.diagnostics = {}
    row.correction_reason = correction.reason
    row.updated_at = utc_now()
    attempt.review_revision = new_revision
    attempt.status = "review"
    attempt.updated_at = utc_now()
    session.execute(delete(ImportBatch).where(ImportBatch.import_id == import_id))
    attempt.batch_count = 0
    session.add(
        ImportReviewEvent(
            id=uuid4(),
            import_id=import_id,
            review_revision=new_revision,
            action="correct_row",
            reason=correction.reason,
            change_payload={"row_number": row.row_number},
            created_at=utc_now(),
        )
    )
    return _row_read(session, row)


def cancel_import(
    session: Session, import_id: UUID, *, expected_revision: int, reason: str
) -> str:
    attempt = session.get(ImportAttempt, import_id)
    if attempt is None:
        raise ImportNotFound
    if attempt.status in {"published", "cancelled", "replaced"}:
        if attempt.status == "cancelled":
            return attempt.status
        raise ImportConflict("This import can no longer be cancelled.")
    if attempt.review_revision != expected_revision:
        raise ImportRevisionConflict
    revision = attempt.review_revision + 1
    advanced = session.execute(
        update(ImportAttempt)
        .where(
            ImportAttempt.id == import_id,
            ImportAttempt.status.in_(("staging", "review", "publishing", "blocked")),
            ImportAttempt.review_revision == expected_revision,
        )
        .values(status="cancelled", review_revision=revision, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(advanced, "rowcount", None) != 1:
        raise ImportRevisionConflict
    attempt.review_revision = revision
    attempt.status = "cancelled"
    attempt.updated_at = utc_now()
    session.execute(delete(ImportBatch).where(ImportBatch.import_id == import_id))
    session.add(
        ImportReviewEvent(
            id=uuid4(),
            import_id=import_id,
            review_revision=revision,
            action="cancel",
            reason=reason.strip() or "Cancelled by user",
            change_payload={},
            created_at=utc_now(),
        )
    )
    return attempt.status


def _import_rows(session: Session, import_id: UUID) -> list[ImportRow]:
    return list(
        session.scalars(
            select(ImportRow)
            .where(ImportRow.import_id == import_id)
            .order_by(ImportRow.row_number)
        )
    )


def publish_position_import(
    session_factory: sessionmaker[Session],
    import_id: UUID,
    *,
    expected_review_revision: int,
) -> UUID:
    def prepare(
        session: Session,
    ) -> tuple[
        UUID,
        date,
        UUID,
        int,
        list[tuple[int, UUID, Decimal, Decimal | None, str]],
    ]:
        attempt = session.get(ImportAttempt, import_id)
        if attempt is None or attempt.account_id is None:
            raise ImportNotFound
        if attempt.status == "published" and attempt.published_snapshot_id is not None:
            return (
                attempt.published_snapshot_id,
                attempt.effective_date,
                attempt.account_id,
                attempt.expected_account_revision or 0,
                [],
            )
        if (
            attempt.status != "review"
            or attempt.review_revision != expected_review_revision
        ):
            raise ImportRevisionConflict
        rows = _import_rows(session, import_id)
        blockers = [
            row for row in rows if not row.excluded and row.row_status != "ready"
        ]
        if blockers:
            raise ImportBlocked(
                f"{len(blockers)} row(s) need correction or explicit exclusion."
            )
        publish_rows = [row for row in rows if not row.excluded]
        if not publish_rows:
            raise ImportBlocked(
                "At least one position must remain in the published snapshot."
            )
        seen: set[UUID] = set()
        values: list[tuple[int, UUID, Decimal, Decimal | None, str]] = []
        for row in publish_rows:
            if (
                row.security_id is None
                or row.normalized_quantity is None
                or row.currency is None
            ):
                raise ImportBlocked(
                    "Every published row needs a security, quantity, and currency."
                )
            if row.security_id in seen:
                raise ImportBlocked(
                    "Duplicate securities must be corrected before publication."
                )
            seen.add(row.security_id)
            security = session.get(Security, row.security_id)
            if security is None or security.currency != row.currency:
                raise ImportBlocked("Position security or currency is no longer valid.")
            if security.security_type == "cash" and row.normalized_price is not None:
                raise ImportBlocked(
                    "Cash rows use an explicit balance and cannot have a price."
                )
            values.append(
                (
                    row.row_number,
                    row.security_id,
                    row.normalized_quantity,
                    row.normalized_price,
                    row.currency,
                )
            )
        expected_account_revision = attempt.expected_account_revision
        if expected_account_revision is None:
            raise ImportBlocked("Import has no captured account revision.")
        snapshot_id = attempt.staging_snapshot_id or uuid4()
        return (
            snapshot_id,
            attempt.effective_date,
            attempt.account_id,
            expected_account_revision,
            values,
        )

    snapshot_id, effective_date, account_id, expected_account_revision, rows = (
        run_database_unit(session_factory, prepare)
    )
    if not rows:
        with session_factory() as session:
            attempt = session.get(ImportAttempt, import_id)
            if (
                attempt
                and attempt.status == "published"
                and attempt.published_snapshot_id
            ):
                return attempt.published_snapshot_id
        raise ImportBlocked("No rows are available for publication.")

    batches = [
        rows[index : index + IMPORT_BATCH_ROWS]
        for index in range(0, len(rows), IMPORT_BATCH_ROWS)
    ]
    snapshot_at = datetime.combine(effective_date, time.min, tzinfo=UTC)
    import_source = f"import:{import_id.hex}"

    for ordinal, batch in enumerate(batches):
        batch_hash = _canonical_hash(
            [
                [
                    str(row_number),
                    str(security_id),
                    str(quantity),
                    str(price) if price is not None else None,
                    currency,
                ]
                for row_number, security_id, quantity, price, currency in batch
            ]
        )

        def stage_batch(
            session: Session,
            *,
            batch_ordinal: int,
            staged_hash: str,
            staged_rows: list[tuple[int, UUID, Decimal, Decimal | None, str]],
        ) -> None:
            attempt = session.get(ImportAttempt, import_id)
            if attempt is None:
                raise ImportNotFound
            transitioned = session.execute(
                update(ImportAttempt)
                .where(
                    ImportAttempt.id == import_id,
                    ImportAttempt.status.in_(("review", "publishing")),
                    ImportAttempt.review_revision == expected_review_revision,
                )
                .values(status="publishing", updated_at=utc_now())
                .execution_options(synchronize_session=False)
            )
            if getattr(transitioned, "rowcount", None) != 1:
                raise ImportConflict("Import is no longer publishable.")
            if attempt.review_revision != expected_review_revision:
                raise ImportRevisionConflict
            if attempt.staging_snapshot_id is None:
                snapshot = PositionSnapshot(
                    id=snapshot_id,
                    account_id=account_id,
                    snapshot_at=snapshot_at,
                    source=import_source,
                    valuation_source=attempt.source_label,
                    status="staging",
                    revision=expected_account_revision + 1,
                )
                session.add(snapshot)
                session.flush()
                attempt.staging_snapshot_id = snapshot.id
            else:
                existing_snapshot = session.get(
                    PositionSnapshot, attempt.staging_snapshot_id
                )
                if existing_snapshot is None:
                    raise ImportConflict("Import staging snapshot is missing.")
            marker = session.scalar(
                select(ImportBatch).where(
                    ImportBatch.import_id == import_id,
                    ImportBatch.purpose == "publish",
                    ImportBatch.review_revision == expected_review_revision,
                    ImportBatch.ordinal == batch_ordinal,
                )
            )
            if marker is not None:
                if marker.payload_hash != staged_hash:
                    raise ImportConflict(
                        "Published batch payload changed after review."
                    )
                return
            target_snapshot_id = attempt.staging_snapshot_id
            now = utc_now()
            for row_number, security_id, quantity, price, currency in staged_rows:
                security = session.get(Security, security_id)
                if security is None:
                    raise ImportBlocked(
                        "Selected security was deleted during import review."
                    )
                with localcontext() as context:
                    context.prec = 80
                    value = (
                        quantity
                        if security.security_type == "cash"
                        else (quantity * price).quantize(
                            Decimal("0.0000000001"), rounding=ROUND_HALF_UP
                        )
                        if price is not None
                        else None
                    )
                    if value is not None and abs(value) >= Decimal("1e18"):
                        raise ImportBlocked("Calculated value exceeds NUMERIC(28,10).")
                session.add(
                    PositionSnapshotLine(
                        id=uuid5(target_snapshot_id, f"row:{row_number}"),
                        snapshot_id=target_snapshot_id,
                        security_id=security_id,
                        unresolved_ref=None,
                        quantity=quantity,
                        reported_value=value,
                        reported_price=None
                        if security.security_type == "cash"
                        else price,
                        currency=currency,
                        original_row_ref=str(row_number),
                        source=attempt.source_label[:100],
                        quality_status="reviewed_import",
                    )
                )
            session.add(
                ImportBatch(
                    id=uuid5(
                        import_id,
                        f"publish:{expected_review_revision}:{batch_ordinal}",
                    ),
                    import_id=import_id,
                    purpose="publish",
                    review_revision=expected_review_revision,
                    ordinal=batch_ordinal,
                    payload_hash=staged_hash,
                    row_count=len(staged_rows),
                    status="complete",
                )
            )
            attempt.status = "publishing"
            attempt.updated_at = now

        run_database_unit(
            session_factory,
            partial(
                stage_batch,
                batch_ordinal=ordinal,
                staged_hash=batch_hash,
                staged_rows=batch,
            ),
        )

    def finalize(session: Session) -> UUID:
        attempt = session.get(ImportAttempt, import_id)
        account = session.get(Account, account_id)
        snapshot = session.get(PositionSnapshot, snapshot_id)
        if attempt is None or account is None or snapshot is None:
            raise ImportNotFound
        if attempt.status == "published" and attempt.published_snapshot_id:
            return attempt.published_snapshot_id
        if (
            attempt.status != "publishing"
            or attempt.review_revision != expected_review_revision
        ):
            raise ImportRevisionConflict
        published = session.execute(
            update(ImportAttempt)
            .where(
                ImportAttempt.id == import_id,
                ImportAttempt.status == "publishing",
                ImportAttempt.review_revision == expected_review_revision,
            )
            .values(
                status="published",
                published_snapshot_id=snapshot_id,
                updated_at=utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(published, "rowcount", None) != 1:
            raise ImportRevisionConflict
        if account.current_position_revision != expected_account_revision:
            raise ImportAccountConflict(
                "Account changed while the import was being staged."
            )
        actual_batches = len(
            list(
                session.scalars(
                    select(ImportBatch.id).where(
                        ImportBatch.import_id == import_id,
                        ImportBatch.purpose == "publish",
                        ImportBatch.review_revision == expected_review_revision,
                    )
                )
            )
        )
        if actual_batches != len(batches):
            raise ImportBlocked("Not all bounded publication batches were staged.")
        now = utc_now()
        updated = session.execute(
            update(Account)
            .where(
                Account.id == account_id,
                Account.current_position_revision == expected_account_revision,
            )
            .values(
                current_position_revision=expected_account_revision + 1,
                current_position_snapshot_id=snapshot_id,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(updated, "rowcount", None) != 1:
            raise ImportAccountConflict(
                "Account changed while the import was being published."
            )
        if account.current_position_snapshot_id is not None:
            previous = session.get(
                PositionSnapshot, account.current_position_snapshot_id
            )
            if previous and previous.status == "accepted":
                previous.status = "superseded"
                previous.updated_at = now
        account.current_position_revision = expected_account_revision + 1
        account.current_position_snapshot_id = snapshot_id
        snapshot.status = "accepted"
        snapshot.accepted_at = now
        snapshot.updated_at = now
        return snapshot_id

    return run_database_unit(session_factory, finalize)


def issuer_create(session: Session, display_name: str) -> Issuer:
    normalized = " ".join(display_name.casefold().split())
    existing = session.scalar(
        select(Issuer).where(Issuer.normalized_name == normalized)
    )
    if existing is not None:
        raise ImportConflict("An issuer with this normalized name already exists.")
    issuer = Issuer(
        id=uuid4(), normalized_name=normalized, display_name=display_name.strip()
    )
    session.add(issuer)
    session.flush()
    return issuer


def security_create(session: Session, data: Any) -> Security:
    if data.issuer_id is not None and session.get(Issuer, data.issuer_id) is None:
        raise ImportNotFound("Issuer not found.")
    ticker = data.display_ticker.strip().upper() if data.display_ticker else None
    if ticker and session.scalar(
        select(Security.id).where(Security.display_ticker == ticker)
    ):
        raise ImportConflict("A security with this ticker already exists.")
    security = Security(
        id=uuid4(),
        security_type=data.security_type,
        display_ticker=ticker,
        name=data.name.strip(),
        issuer_id=data.issuer_id,
        currency=data.currency,
    )
    session.add(security)
    session.flush()
    if data.identifier_namespace and data.identifier_value:
        value = data.identifier_value.strip()
        session.add(
            SecurityIdentifier(
                id=uuid4(),
                security_id=security.id,
                namespace=data.identifier_namespace.strip().casefold(),
                exchange=data.identifier_exchange.strip().upper(),
                value=value,
                normalized_value=value.upper(),
                valid_from=date.today(),
                valid_to=None,
                source="manual_review",
                review_status="reviewed",
            )
        )
    session.flush()
    return security


def assign_security_issuer(
    session: Session,
    security_id: UUID,
    issuer_id: UUID | None,
    expected_issuer_id: UUID | None,
    reason: str,
) -> Security:
    security = session.get(Security, security_id)
    if security is None:
        raise ImportNotFound
    if security.issuer_id != expected_issuer_id:
        raise ImportRevisionConflict
    if issuer_id is not None and session.get(Issuer, issuer_id) is None:
        raise ImportNotFound("Issuer not found.")
    previous = security.issuer_id
    security.issuer_id = issuer_id
    session.add(
        __import__("app.db.models", fromlist=["IssuerMappingEvent"]).IssuerMappingEvent(
            id=uuid4(),
            security_id=security_id,
            previous_issuer_id=previous,
            new_issuer_id=issuer_id,
            reason=reason.strip(),
            changed_at=utc_now(),
        )
    )
    session.flush()
    return security


def record_manual_quote(session: Session, data: Any) -> Quote:
    security = session.get(Security, data.security_id)
    if security is None:
        raise ImportNotFound("Security not found.")
    if security.currency != data.currency:
        raise ImportBlocked("Quote currency must match the selected security.")
    if data.as_of.date() > date.today():
        raise ImportBlocked("Future quote observations are not accepted.")
    try:
        price = _decimal(data.price, required=True, nonnegative=True)
    except ValueError as exc:
        raise ImportBlocked(str(exc)) from exc
    quote = Quote(
        id=uuid4(),
        security_id=security.id,
        as_of=data.as_of,
        price=price,
        currency=data.currency,
        source=f"manual:{uuid4().hex}",
        fetched_at=utc_now(),
        quality_status="reviewed",
        provider_metadata={"reviewed_override": True, "reason": data.reason.strip()},
    )
    session.add(quote)
    session.flush()
    return quote
