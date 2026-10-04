"""Reviewed bank/card CSV imports and deterministic spending workflows."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.contracts import (
    CategoryRuleCreate,
    SpendingCategoryCreate,
    TransactionImportAction,
    TransactionManualCreate,
    TransactionPatch,
    TransactionRowCorrection,
    TransactionSplitsReplace,
    TransferCreate,
)
from app.db.models import (
    Account,
    ActiveTransferTransaction,
    FinancialTransaction,
    MerchantCategoryRule,
    PrivateFile,
    SpendingCategory,
    TransactionImport,
    TransactionProviderIdentity,
    TransactionReviewEvent,
    TransactionSplit,
    TransferMatch,
    utc_now,
)
from app.db.transactions import run_database_unit
from app.storage.file_store import FileStore

TRANSACTION_PARSER_VERSION = "bank-card-csv/1"
MAX_TRANSACTION_ROWS = 500
MAX_TRANSACTION_REVIEW_BYTES = 2_000_000
_AMOUNT = re.compile(r"^-?\d{1,14}(?:\.\d{1,10})?$")
_REQUIRED = {"posted_date", "amount", "description"}
_MAPPED_FIELDS = _REQUIRED | {"transaction_date", "currency", "raw_type", "provider_id"}


class TransactionError(ValueError):
    """Safe transaction workflow failure."""


class TransactionNotFound(TransactionError):
    """A requested import, row, category or transaction does not exist."""


class TransactionConflict(TransactionError):
    """The requested operation conflicts with source identity or revision."""


class TransactionBlocked(TransactionError):
    """The operation cannot proceed while rows require user review."""


def _advance_revision(
    session: Session,
    model: Any,
    identity: UUID,
    *,
    expected: int,
    extra: tuple[Any, ...] = (),
) -> None:
    """Claim a revision in the database before writing dependent audit/data rows."""
    result = session.execute(
        update(model)
        .where(model.id == identity, model.revision == expected, *extra)
        .values(revision=expected + 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", None) != 1:
        raise TransactionConflict("Record changed; reload before editing.")


def _advance_import_review(
    session: Session, record: TransactionImport, expected: int
) -> None:
    result = session.execute(
        update(TransactionImport)
        .where(
            TransactionImport.id == record.id,
            TransactionImport.status == "review",
            TransactionImport.review_revision == expected,
        )
        .values(review_revision=expected + 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", None) != 1:
        raise TransactionConflict("Transaction import review changed; reload it.")
    record.review_revision = expected + 1
    record.updated_at = utc_now()


def normalize_merchant(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())[:200]


def _file_name(value: str) -> str:
    basename = Path(value.replace("\\", "/")).name
    clean = "".join(ch for ch in basename if ch >= " " and ch != "\x7f").strip()[:200]
    if not clean.casefold().endswith(".csv"):
        raise TransactionError("Upload a CSV file.")
    return clean


def _date(value: str | None) -> date | None:
    if not value or not value.strip():
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


def _amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    raw = value.strip().replace("$", "").replace(",", "").replace(" ", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    if not _AMOUNT.fullmatch(raw):
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _fingerprint(
    account_id: UUID,
    posted_date: date | None,
    amount: Decimal | None,
    currency: str | None,
    merchant: str,
) -> str:
    parts = (
        str(account_id),
        posted_date.isoformat() if posted_date else "",
        str(amount) if amount is not None else "",
        currency or "",
        merchant,
    )
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


def _private_file(
    session: Session, *, digest: str, key: str, filename: str, byte_size: int
) -> PrivateFile:
    existing = session.scalar(
        select(PrivateFile).where(PrivateFile.content_hash == digest)
    )
    if existing is not None:
        if existing.content_type not in {"text/csv", "application/csv"}:
            raise TransactionConflict(
                "This source has a conflicting stored media type."
            )
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
    file_store: FileStore,
    *,
    content: bytes,
    filename: str,
    account_id: UUID,
    source_label: str,
    idempotency_key: str,
    mapping: dict[str, str],
    statement_start: date | None = None,
    statement_end: date | None = None,
    max_rows: int = MAX_TRANSACTION_ROWS,
    max_file_bytes: int = 5_000_000,
) -> tuple[UUID, bool]:
    """Validate CSV outside DB writes, then persist a bounded private review."""
    safe_name = _file_name(filename)
    label = source_label.strip()
    if not 1 <= len(label) <= 100:
        raise TransactionError("Source label must contain 1 to 100 characters.")
    if not 1 <= len(idempotency_key) <= 128:
        raise TransactionError("A valid idempotency key is required.")
    if statement_start and statement_end and statement_start > statement_end:
        raise TransactionError("Statement start date must not follow its end date.")
    if not content or len(content) > max_file_bytes:
        raise TransactionError("CSV is empty or exceeds the configured size limit.")
    if max_rows < 1 or max_rows > MAX_TRANSACTION_ROWS:
        raise TransactionError("Transaction imports are limited to 500 rows.")
    if not _REQUIRED.issubset(mapping) or any(
        not isinstance(v, str) for v in mapping.values()
    ):
        raise TransactionError("Map posted_date, amount and description columns.")

    if set(mapping) - _MAPPED_FIELDS or len(set(mapping.values())) != len(mapping):
        raise TransactionError("Map each supported transaction field to one column.")
    if b"\x00" in content:
        raise TransactionError("CSV cannot contain NUL characters.")

    with session_factory() as session:
        account = session.get(Account, account_id)
        if account is None or not account.active:
            raise TransactionNotFound("Active account not found.")
        base_currency = account.base_currency

    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames
        if (
            not headers
            or len(headers) > 100
            or any(not header.strip() for header in headers)
            or len(set(headers)) != len(headers)
        ):
            raise TransactionError(
                "CSV needs between 1 and 100 unique, nonempty headers."
            )
        missing = [name for name in mapping.values() if name not in headers]
        if missing:
            raise TransactionError("A selected source column is missing.")
        parsed_rows: list[dict[str, Any]] = []
        for row_number, raw in enumerate(reader, start=1):
            if row_number > max_rows:
                raise TransactionError("Transaction CSV contains more than 500 rows.")
            missing_fields = any(value is None for value in raw.values())
            extra_fields = raw.pop(None, [])
            raw_values: dict[str, Any] = {
                str(key): str(value or "") for key, value in raw.items()
            }
            if extra_fields:
                raw_values["__extra_fields__"] = [
                    str(value or "") for value in extra_fields
                ]
            values = {
                key: raw_values.get(header, "").strip()
                for key, header in mapping.items()
            }
            if any(
                len(value) > 2000
                for value in raw_values.values()
                if isinstance(value, str)
            ):
                raise TransactionError(f"CSV row {row_number} has an oversized field.")
            for field, maximum in {
                "posted_date": 100,
                "transaction_date": 100,
                "amount": 100,
                "currency": 40,
                "raw_type": 120,
                "provider_id": 200,
            }.items():
                if len(values.get(field, "")) > maximum:
                    raise TransactionError(
                        f"CSV row {row_number} {field} exceeds {maximum} characters."
                    )
            posted = _date(values.get("posted_date"))
            transaction_date = _date(values.get("transaction_date"))
            amount = _amount(values.get("amount"))
            raw_currency = values.get("currency", "")
            currency = (raw_currency or base_currency).upper()
            description = values.get("description", "")
            diagnostics: dict[str, Any] = {}
            status = "ready"
            if extra_fields or missing_fields:
                status = "needs_review"
                diagnostics["columns"] = "row_does_not_match_header"
            if values.get("transaction_date") and transaction_date is None:
                status = "needs_review"
                diagnostics["transaction_date"] = "invalid"
            if posted is None:
                status = "needs_review"
                diagnostics["posted_date"] = "missing_or_invalid"
            if amount is None:
                status = "needs_review"
                diagnostics["amount"] = "missing_or_invalid"
            if not description.strip():
                status = "needs_review"
                diagnostics["description"] = "missing"
            if not re.fullmatch(r"[A-Z]{3}", currency):
                status = "needs_review"
                diagnostics["currency"] = "missing_or_invalid"
            if not raw_currency:
                diagnostics["currency_assumed_from_account"] = True
            merchant = normalize_merchant(description)
            parsed_rows.append(
                {
                    "row_number": row_number,
                    "raw_payload": raw_values,
                    "raw_posted_date": values.get("posted_date"),
                    "posted_date": posted,
                    "raw_transaction_date": values.get("transaction_date"),
                    "transaction_date": transaction_date,
                    "raw_amount": values.get("amount"),
                    "amount": amount,
                    "raw_currency": raw_currency or None,
                    "currency": currency
                    if re.fullmatch(r"[A-Z]{3}", currency)
                    else None,
                    "raw_description": description,
                    "description": description,
                    "raw_type": values.get("raw_type") or None,
                    "provider_transaction_id": values.get("provider_id") or None,
                    "normalized_merchant": merchant,
                    "fingerprint": _fingerprint(
                        account_id, posted, amount, currency, merchant
                    ),
                    "status": status,
                    "diagnostics": diagnostics,
                }
            )
    except (UnicodeDecodeError, csv.Error) as exc:
        raise TransactionError("CSV must be well-formed UTF-8 text.") from exc
    if not parsed_rows:
        raise TransactionError("CSV contains no transaction rows.")
    # These rows are committed together. UTF-8 upload size does not bound the
    # escaped JSON write size; bound memory and persistence latency for the import
    # limit for normalized columns, audit records, identities, and index writes.
    review_bytes = sum(
        len(json.dumps(row, ensure_ascii=True, default=str).encode("utf-8"))
        for row in parsed_rows
    )
    if review_bytes > MAX_TRANSACTION_REVIEW_BYTES:
        raise TransactionError(
            "Normalized transaction rows exceed the 2 MB write budget; "
            "split the CSV into smaller imports. Source values are not truncated."
        )

    key, digest = file_store.put(content)
    now = utc_now()

    def create(session: Session) -> tuple[UUID, bool]:
        by_key = session.scalar(
            select(TransactionImport).where(
                TransactionImport.idempotency_key == idempotency_key
            )
        )
        if by_key is not None:
            if (
                by_key.file_sha256 != digest
                or by_key.account_id != account_id
                or by_key.source_label != label
                or by_key.statement_start != statement_start
                or by_key.statement_end != statement_end
                or by_key.diagnostics.get("mapping") != mapping
            ):
                raise TransactionConflict(
                    "Idempotency key was already used for another import."
                )
            return by_key.id, True
        source = _private_file(
            session, digest=digest, key=key, filename=safe_name, byte_size=len(content)
        )
        old = session.scalar(
            select(TransactionImport)
            .where(
                TransactionImport.account_id == account_id,
                TransactionImport.source_label == label,
                TransactionImport.file_sha256 == digest,
                TransactionImport.status != "cancelled",
            )
            .order_by(TransactionImport.created_at)
        )
        if old is not None:
            if (
                old.diagnostics.get("mapping") != mapping
                or old.statement_start != statement_start
                or old.statement_end != statement_end
            ):
                raise TransactionConflict(
                    "This source already has a different interpretation; "
                    "cancel the unpublished review before importing again."
                )
            return old.id, True

        # Review classifications depend on this transaction's database snapshot.
        # A serialization retry must recompute them from pristine parsed input.
        rows_to_stage = deepcopy(parsed_rows)
        # Keep repeated native IDs in the source for explicit row review.
        seen_provider_ids: dict[str, int] = {}
        for row in rows_to_stage:
            provider_id = row["provider_transaction_id"]
            if provider_id and provider_id in seen_provider_ids:
                row["status"] = "needs_review"
                row["diagnostics"]["repeated_provider_id_in_file"] = True
                row["diagnostics"]["repeated_provider_row_number"] = seen_provider_ids[
                    provider_id
                ]
            elif provider_id:
                seen_provider_ids[provider_id] = row["row_number"]
            if row["status"] != "ready":
                continue
            existing: FinancialTransaction | None = None
            if provider_id:
                identity = session.scalar(
                    select(TransactionProviderIdentity).where(
                        TransactionProviderIdentity.account_id == account_id,
                        TransactionProviderIdentity.source_label == label,
                        TransactionProviderIdentity.provider_transaction_id
                        == provider_id,
                    )
                )
                existing = (
                    session.get(FinancialTransaction, identity.transaction_id)
                    if identity
                    else None
                )
            else:
                matches = list(
                    session.scalars(
                        select(FinancialTransaction)
                        .where(
                            FinancialTransaction.account_id == account_id,
                            FinancialTransaction.posted_date == row["posted_date"],
                            FinancialTransaction.amount == row["amount"],
                            FinancialTransaction.currency == row["currency"],
                            FinancialTransaction.normalized_merchant
                            == row["normalized_merchant"],
                            FinancialTransaction.status == "published",
                        )
                        .limit(6)
                    )
                )
                if matches:
                    row["status"] = "ambiguous"
                    row["diagnostics"]["possible_duplicate_ids"] = [
                        str(item.id) for item in matches[:5]
                    ]
            if existing is not None:
                identical = (
                    existing.posted_date == row["posted_date"]
                    and existing.transaction_date == row["transaction_date"]
                    and existing.raw_type == row["raw_type"]
                    and existing.amount == row["amount"]
                    and existing.currency == row["currency"]
                    and existing.raw_description == row["raw_description"]
                )
                if identical:
                    row["status"] = "duplicate"
                    row["diagnostics"]["duplicate_of"] = str(existing.id)
                else:
                    row["status"] = "needs_review"
                    row["diagnostics"]["native_id_conflict"] = str(existing.id)
                    row["diagnostics"]["possible_duplicate_ids"] = [str(existing.id)]

        import_row = TransactionImport(
            id=uuid4(),
            file_id=source.id,
            account_id=account_id,
            source_label=label,
            parser_version=TRANSACTION_PARSER_VERSION,
            file_sha256=digest,
            idempotency_key=idempotency_key,
            statement_start=statement_start,
            statement_end=statement_end,
            review_revision=1,
            row_count=len(rows_to_stage),
            status="review",
            diagnostics={"mapping": mapping, "row_count": len(rows_to_stage)},
            created_at=now,
            updated_at=now,
        )
        session.add(import_row)
        session.flush()
        row_ids_by_number: dict[int, UUID] = {}
        for row in rows_to_stage:
            repeated_row_number = row["diagnostics"].get("repeated_provider_row_number")
            if repeated_row_number is not None:
                earlier_id = row_ids_by_number.get(int(repeated_row_number))
                if earlier_id is not None:
                    row["diagnostics"]["possible_duplicate_ids"] = [str(earlier_id)]
            transaction_id = uuid4()
            rule = session.scalar(
                select(MerchantCategoryRule)
                .where(
                    MerchantCategoryRule.normalized_merchant
                    == row["normalized_merchant"],
                    MerchantCategoryRule.active.is_(True),
                )
                .order_by(
                    MerchantCategoryRule.priority, MerchantCategoryRule.version.desc()
                )
            )
            transaction = FinancialTransaction(
                id=transaction_id,
                account_id=account_id,
                import_id=import_row.id,
                source_label=label,
                provider_transaction_id=row["provider_transaction_id"],
                row_number=row["row_number"],
                raw_posted_date=row["raw_posted_date"],
                posted_date=row["posted_date"],
                raw_transaction_date=row["raw_transaction_date"],
                transaction_date=row["transaction_date"],
                raw_amount=row["raw_amount"],
                amount=row["amount"],
                raw_currency=row["raw_currency"],
                currency=row["currency"],
                raw_description=row["raw_description"],
                description=row["description"],
                normalized_merchant=row["normalized_merchant"],
                raw_type=row["raw_type"],
                raw_payload=row["raw_payload"],
                fingerprint=row["fingerprint"],
                status=row["status"],
                identity_resolution=None,
                duplicate_of_transaction_id=UUID(row["diagnostics"]["duplicate_of"])
                if row["diagnostics"].get("duplicate_of")
                else None,
                classification="unclassified",
                category_id=rule.category_id if rule else None,
                category_source="rule" if rule else "unclassified",
                revision=1,
                diagnostics=row["diagnostics"],
                created_at=now,
                updated_at=now,
            )
            session.add(transaction)
            row_ids_by_number[row["row_number"]] = transaction_id
        session.flush()
        return import_row.id, False

    try:
        return run_database_unit(session_factory, create)
    except IntegrityError as exc:
        raise TransactionConflict(
            "Transaction import identity conflicted; retry the preview."
        ) from exc


def _event(
    session: Session,
    transaction: FinancialTransaction,
    *,
    action: str,
    reason: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    session.add(
        TransactionReviewEvent(
            id=uuid4(),
            transaction_id=transaction.id,
            import_id=transaction.import_id,
            review_revision=transaction.revision,
            action=action,
            reason=reason,
            change_payload={"before": before, "after": after},
            created_at=utc_now(),
        )
    )


def read_import(session: Session, import_id: UUID) -> dict[str, Any]:
    record = session.get(TransactionImport, import_id)
    if record is None:
        raise TransactionNotFound("Transaction import not found.")
    rows = list(
        session.scalars(
            select(FinancialTransaction)
            .where(FinancialTransaction.import_id == import_id)
            .order_by(FinancialTransaction.row_number)
            .limit(MAX_TRANSACTION_ROWS)
        )
    )
    return {
        "id": record.id,
        "account_id": record.account_id,
        "source_label": record.source_label,
        "statement_start": record.statement_start,
        "statement_end": record.statement_end,
        "parser_version": record.parser_version,
        "status": record.status,
        "review_revision": record.review_revision,
        "row_count": record.row_count,
        "diagnostics": record.diagnostics,
        "rows": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "raw_payload": row.raw_payload,
                "raw_posted_date": row.raw_posted_date,
                "posted_date": row.posted_date,
                "raw_transaction_date": row.raw_transaction_date,
                "transaction_date": row.transaction_date,
                "raw_amount": row.raw_amount,
                "amount": str(row.amount) if row.amount is not None else None,
                "raw_currency": row.raw_currency,
                "currency": row.currency,
                "raw_description": row.raw_description,
                "description": row.description,
                "raw_type": row.raw_type,
                "provider_transaction_id": row.provider_transaction_id,
                "status": row.status,
                "diagnostics": row.diagnostics,
                "duplicate_candidates": [
                    UUID(value)
                    for value in row.diagnostics.get("possible_duplicate_ids", [])
                ],
            }
            for row in rows
        ],
    }


def correct_import_row(
    session: Session,
    import_id: UUID,
    row_id: UUID,
    data: TransactionRowCorrection,
) -> dict[str, Any]:
    record = session.get(TransactionImport, import_id)
    row = session.get(FinancialTransaction, row_id)
    if record is None or row is None or row.import_id != import_id:
        raise TransactionNotFound("Transaction import row not found.")
    if record.status != "review":
        raise TransactionConflict("Only an unpublished review can be corrected.")
    if data.expected_review_revision != record.review_revision:
        raise TransactionConflict("Transaction import review changed; reload it.")
    _advance_import_review(session, record, data.expected_review_revision)
    before = {
        "posted_date": row.posted_date.isoformat() if row.posted_date else None,
        "transaction_date": row.transaction_date.isoformat()
        if row.transaction_date
        else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "description": row.description,
        "provider_transaction_id": row.provider_transaction_id,
        "status": row.status,
    }
    changes = data.model_dump(
        exclude={
            "expected_review_revision",
            "reason",
            "identity_resolution",
            "duplicate_of_transaction_id",
        },
        exclude_unset=True,
    )
    if "description" in changes and changes["description"] is None:
        raise TransactionError("Corrected description cannot be null.")
    if "amount" in changes:
        parsed = _amount(changes["amount"])
        if parsed is None:
            raise TransactionError("Corrected amount is invalid.")
        row.amount = parsed
    for field in (
        "posted_date",
        "transaction_date",
        "currency",
        "description",
        "provider_transaction_id",
        "raw_type",
    ):
        if field in changes:
            setattr(row, field, changes[field])
    if data.identity_resolution in {"duplicate", "update"} and (
        row.posted_date is None
        or row.amount is None
        or row.currency is None
        or not row.description.strip()
    ):
        raise TransactionError(
            "Resolve posted date, amount, currency and description before "
            "identity resolution."
        )
    merchant = normalize_merchant(row.description)
    row.normalized_merchant = merchant
    row.fingerprint = _fingerprint(
        row.account_id, row.posted_date, row.amount, row.currency, merchant
    )
    if data.identity_resolution in {"duplicate", "update"}:
        target_id = data.duplicate_of_transaction_id
        if target_id is None or target_id not in [
            UUID(value) for value in row.diagnostics.get("possible_duplicate_ids", [])
        ]:
            raise TransactionError("Choose one of the displayed duplicate candidates.")
        if data.identity_resolution == "update" and not row.provider_transaction_id:
            raise TransactionError(
                "Only a matching native provider ID can update an existing transaction."
            )
        target = session.get(FinancialTransaction, target_id)
        if target is None or target.account_id != row.account_id:
            raise TransactionError("Selected duplicate candidate is unavailable.")
        if data.identity_resolution == "update" and (
            target.source_label != row.source_label
            or target.provider_transaction_id != row.provider_transaction_id
        ):
            raise TransactionError(
                "Only the same scoped provider ID can update an existing transaction."
            )
        if data.identity_resolution == "update":
            row.diagnostics = {
                **row.diagnostics,
                "expected_target_revision": target.revision,
            }
        row.status = (
            "duplicate" if data.identity_resolution == "duplicate" else "update"
        )
        row.duplicate_of_transaction_id = target_id
        row.identity_resolution = data.identity_resolution
    else:
        row.identity_resolution = data.identity_resolution or row.identity_resolution
        repeated_id_row = (
            session.scalar(
                select(FinancialTransaction)
                .where(
                    FinancialTransaction.import_id == import_id,
                    FinancialTransaction.id != row.id,
                    FinancialTransaction.provider_transaction_id
                    == row.provider_transaction_id,
                )
                .limit(1)
            )
            if row.provider_transaction_id
            else None
        )
        if (
            row.posted_date is None
            or row.amount is None
            or row.currency is None
            or not row.description.strip()
        ):
            row.status = "needs_review"
        elif repeated_id_row is not None:
            row.status = "needs_review"
            row.diagnostics["repeated_provider_id_in_file"] = True
            row.diagnostics["possible_duplicate_ids"] = [str(repeated_id_row.id)]
        elif row.status == "ambiguous" and row.identity_resolution != "keep":
            row.status = "ambiguous"
        else:
            row.status = "ready"
            row.diagnostics = {
                key: value
                for key, value in row.diagnostics.items()
                if key in {"currency_assumed_from_account"}
            }
    _advance_revision(session, FinancialTransaction, row.id, expected=row.revision)
    row.revision += 1
    row.updated_at = utc_now()
    record.updated_at = utc_now()
    after = {
        "posted_date": row.posted_date.isoformat() if row.posted_date else None,
        "transaction_date": row.transaction_date.isoformat()
        if row.transaction_date
        else None,
        "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "description": row.description,
        "provider_transaction_id": row.provider_transaction_id,
        "status": row.status,
        "identity_resolution": row.identity_resolution,
        "duplicate_of_transaction_id": str(row.duplicate_of_transaction_id)
        if row.duplicate_of_transaction_id
        else None,
    }
    _event(
        session, row, action="correct", reason=data.reason, before=before, after=after
    )
    return {
        "id": row.id,
        "row_number": row.row_number,
        "raw_payload": row.raw_payload,
        "raw_posted_date": row.raw_posted_date,
        "posted_date": row.posted_date,
        "raw_transaction_date": row.raw_transaction_date,
        "transaction_date": row.transaction_date,
        "raw_amount": row.raw_amount,
        "amount": str(row.amount) if row.amount is not None else None,
        "raw_currency": row.raw_currency,
        "currency": row.currency,
        "raw_description": row.raw_description,
        "description": row.description,
        "raw_type": row.raw_type,
        "provider_transaction_id": row.provider_transaction_id,
        "status": row.status,
        "diagnostics": row.diagnostics,
        "duplicate_candidates": [
            UUID(value) for value in row.diagnostics.get("possible_duplicate_ids", [])
        ],
    }


def publish_import(
    session_factory: sessionmaker[Session],
    import_id: UUID,
    data: TransactionImportAction,
) -> str:
    """Publish at most 500 accepted rows and the marker in one bounded write."""

    def publish(session: Session) -> str:
        record = session.get(TransactionImport, import_id)
        if record is None:
            raise TransactionNotFound("Transaction import not found.")
        if record.status == "committed":
            return record.status
        if record.status != "review":
            raise TransactionConflict("Transaction import is no longer reviewable.")
        if record.review_revision != data.expected_review_revision:
            raise TransactionConflict("Transaction import review changed; reload it.")
        advanced = session.execute(
            update(TransactionImport)
            .where(
                TransactionImport.id == import_id,
                TransactionImport.status == "review",
                TransactionImport.review_revision == data.expected_review_revision,
            )
            .values(status="committed", updated_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        if getattr(advanced, "rowcount", None) != 1:
            raise TransactionConflict("Transaction import review changed; reload it.")
        rows = list(
            session.scalars(
                select(FinancialTransaction)
                .where(FinancialTransaction.import_id == import_id)
                .order_by(FinancialTransaction.row_number)
                .limit(MAX_TRANSACTION_ROWS + 1)
            )
        )
        if len(rows) != record.row_count:
            raise TransactionBlocked("Transaction import rows are incomplete.")
        blocked = [
            row for row in rows if row.status not in {"ready", "duplicate", "update"}
        ]
        if blocked:
            raise TransactionBlocked(
                "Resolve every invalid or ambiguous row before publishing."
            )
        if any(
            row.posted_date is None
            or row.amount is None
            or row.currency is None
            or not row.description.strip()
            for row in rows
        ):
            raise TransactionBlocked(
                "Resolve posted date, amount, currency and description before "
                "publishing."
            )
        now = utc_now()
        for row in rows:
            if row.status == "duplicate":
                continue
            if row.status == "update":
                existing = session.get(
                    FinancialTransaction, row.duplicate_of_transaction_id
                )
                if existing is None or existing.status != "published":
                    raise TransactionConflict(
                        "The selected provider transaction no longer exists."
                    )
                identity = session.scalar(
                    select(TransactionProviderIdentity).where(
                        TransactionProviderIdentity.account_id == row.account_id,
                        TransactionProviderIdentity.source_label == row.source_label,
                        TransactionProviderIdentity.provider_transaction_id
                        == row.provider_transaction_id,
                        TransactionProviderIdentity.transaction_id == existing.id,
                    )
                )
                if identity is None:
                    raise TransactionConflict(
                        "The selected provider identity changed after review."
                    )
                expected_target_revision = row.diagnostics.get(
                    "expected_target_revision"
                )
                if expected_target_revision is None or existing.revision != int(
                    expected_target_revision
                ):
                    raise TransactionConflict(
                        "The selected transaction changed after review; "
                        "review it again."
                    )
                financial_fields_changed = (
                    existing.posted_date != row.posted_date
                    or existing.transaction_date != row.transaction_date
                    or existing.amount != row.amount
                    or existing.currency != row.currency
                )
                if financial_fields_changed:
                    has_splits = session.scalar(
                        select(TransactionSplit.id)
                        .where(TransactionSplit.transaction_id == existing.id)
                        .limit(1)
                    )
                    has_transfer = session.scalar(
                        select(ActiveTransferTransaction.transaction_id)
                        .where(ActiveTransferTransaction.transaction_id == existing.id)
                        .limit(1)
                    )
                    if has_splits is not None or has_transfer is not None:
                        raise TransactionBlocked(
                            "Reconcile splits or the confirmed transfer before "
                            "changing this transaction's amount, currency or date."
                        )
                _advance_revision(
                    session,
                    FinancialTransaction,
                    existing.id,
                    expected=int(expected_target_revision),
                    extra=(FinancialTransaction.status == "published",),
                )
                before = {
                    "posted_date": existing.posted_date.isoformat()
                    if existing.posted_date
                    else None,
                    "transaction_date": existing.transaction_date.isoformat()
                    if existing.transaction_date
                    else None,
                    "amount": str(existing.amount)
                    if existing.amount is not None
                    else None,
                    "currency": existing.currency,
                    "raw_description": existing.raw_description,
                    "raw_type": existing.raw_type,
                }
                existing.posted_date = row.posted_date
                existing.transaction_date = row.transaction_date
                existing.amount = row.amount
                existing.currency = row.currency
                existing.raw_posted_date = row.raw_posted_date
                existing.raw_transaction_date = row.raw_transaction_date
                existing.raw_amount = row.raw_amount
                existing.raw_currency = row.raw_currency
                existing.raw_description = row.raw_description
                existing.description = row.description
                existing.raw_type = row.raw_type
                existing.normalized_merchant = row.normalized_merchant
                existing.fingerprint = row.fingerprint
                existing.revision += 1
                existing.updated_at = now
                _event(
                    session,
                    existing,
                    action="provider_update",
                    reason=data.reason,
                    before=before,
                    after={
                        "posted_date": row.posted_date.isoformat()
                        if row.posted_date
                        else None,
                        "transaction_date": row.transaction_date.isoformat()
                        if row.transaction_date
                        else None,
                        "amount": str(row.amount) if row.amount is not None else None,
                        "currency": row.currency,
                        "raw_description": row.raw_description,
                        "raw_type": row.raw_type,
                        "source_import_id": str(import_id),
                    },
                )
                row.status = "duplicate"
                continue
            if row.provider_transaction_id:
                identity = session.scalar(
                    select(TransactionProviderIdentity).where(
                        TransactionProviderIdentity.account_id == row.account_id,
                        TransactionProviderIdentity.source_label == row.source_label,
                        TransactionProviderIdentity.provider_transaction_id
                        == row.provider_transaction_id,
                    )
                )
                existing = (
                    session.get(FinancialTransaction, identity.transaction_id)
                    if identity
                    else None
                )
                if existing is not None:
                    same = (
                        existing.posted_date == row.posted_date
                        and existing.transaction_date == row.transaction_date
                        and existing.raw_type == row.raw_type
                        and existing.amount == row.amount
                        and existing.currency == row.currency
                        and existing.raw_description == row.raw_description
                    )
                    if same:
                        row.status = "duplicate"
                        row.duplicate_of_transaction_id = existing.id
                        continue
                    if (
                        row.status != "update"
                        or row.duplicate_of_transaction_id != existing.id
                    ):
                        raise TransactionConflict(
                            "A provider transaction ID changed since review."
                        )
                else:
                    session.add(
                        TransactionProviderIdentity(
                            id=uuid4(),
                            account_id=row.account_id,
                            source_label=row.source_label,
                            provider_transaction_id=row.provider_transaction_id,
                            transaction_id=row.id,
                        )
                    )
            elif row.identity_resolution != "keep":
                collision_id = session.scalar(
                    select(FinancialTransaction.id)
                    .where(
                        FinancialTransaction.account_id == row.account_id,
                        FinancialTransaction.posted_date == row.posted_date,
                        FinancialTransaction.amount == row.amount,
                        FinancialTransaction.currency == row.currency,
                        FinancialTransaction.normalized_merchant
                        == row.normalized_merchant,
                        FinancialTransaction.status == "published",
                        FinancialTransaction.import_id != import_id,
                    )
                    .limit(1)
                )
                if collision_id is not None:
                    raise TransactionConflict(
                        "A possible duplicate appeared; reload and review."
                    )
            row.status = "published"
            row.published_at = now
            row.updated_at = now
        record.status = "committed"
        record.updated_at = now
        session.add(
            TransactionReviewEvent(
                id=uuid4(),
                transaction_id=rows[0].id,
                import_id=record.id,
                review_revision=record.review_revision,
                action="publish",
                reason=data.reason,
                change_payload={
                    "published_count": sum(row.status == "published" for row in rows)
                },
                created_at=now,
            )
        )
        session.flush()
        return record.status

    return run_database_unit(session_factory, publish)


def cancel_import(
    session: Session, import_id: UUID, data: TransactionImportAction
) -> str:
    record = session.get(TransactionImport, import_id)
    if record is None:
        raise TransactionNotFound("Transaction import not found.")
    if record.status != "review":
        raise TransactionConflict("Only an unpublished review can be cancelled.")
    if record.review_revision != data.expected_review_revision:
        raise TransactionConflict("Transaction import review changed; reload it.")
    advanced = session.execute(
        update(TransactionImport)
        .where(
            TransactionImport.id == import_id,
            TransactionImport.status == "review",
            TransactionImport.review_revision == data.expected_review_revision,
        )
        .values(status="cancelled", updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(advanced, "rowcount", None) != 1:
        raise TransactionConflict("Transaction import review changed; reload it.")
    record.status = "cancelled"
    record.updated_at = utc_now()
    rows = list(
        session.scalars(
            select(FinancialTransaction).where(
                FinancialTransaction.import_id == import_id
            )
        )
    )
    for row in rows:
        row.status = "cancelled"
        row.updated_at = utc_now()
    if rows:
        _event(
            session,
            rows[0],
            action="cancel",
            reason=data.reason,
            before={"status": "review"},
            after={"status": "cancelled"},
        )
    return record.status


def create_category(session: Session, data: SpendingCategoryCreate) -> SpendingCategory:
    existing = session.scalar(
        select(SpendingCategory).where(SpendingCategory.slug == data.slug)
    )
    if existing is not None:
        raise TransactionConflict("A category with this slug already exists.")
    row = SpendingCategory(
        id=uuid4(),
        slug=data.slug,
        display_name=data.display_name,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def create_category_rule(
    session: Session, data: CategoryRuleCreate
) -> MerchantCategoryRule:
    category = session.get(SpendingCategory, data.category_id)
    if category is None:
        raise TransactionNotFound("Category not found.")
    normalized = normalize_merchant(data.merchant)
    if not normalized:
        raise TransactionError("Merchant must contain letters or numbers.")
    versions = session.scalars(
        select(MerchantCategoryRule.version).where(
            MerchantCategoryRule.normalized_merchant == normalized
        )
    )
    version = max(versions, default=0) + 1
    for rule in session.scalars(
        select(MerchantCategoryRule).where(
            MerchantCategoryRule.normalized_merchant == normalized,
            MerchantCategoryRule.active.is_(True),
        )
    ):
        rule.active = False
    row = MerchantCategoryRule(
        id=uuid4(),
        normalized_merchant=normalized,
        category_id=category.id,
        priority=data.priority,
        version=version,
        active=True,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def _transaction_reads(
    session: Session, rows: list[FinancialTransaction]
) -> dict[UUID, dict[str, Any]]:
    """Load related display data once for a bounded transaction result set."""
    if not rows:
        return {}
    identifiers = [row.id for row in rows]
    category_ids = {row.category_id for row in rows if row.category_id is not None}
    categories = {
        category.id: category
        for category in session.scalars(
            select(SpendingCategory).where(SpendingCategory.id.in_(category_ids))
        )
    }
    split_counts = {
        identity: count
        for identity, count in session.execute(
            select(TransactionSplit.transaction_id, func.count(TransactionSplit.id))
            .where(TransactionSplit.transaction_id.in_(identifiers))
            .group_by(TransactionSplit.transaction_id)
        )
    }
    transfer_ids = {
        transaction_id: transfer_id
        for transaction_id, transfer_id in session.execute(
            select(
                ActiveTransferTransaction.transaction_id,
                ActiveTransferTransaction.transfer_id,
            ).where(ActiveTransferTransaction.transaction_id.in_(identifiers))
        )
    }
    result: dict[UUID, dict[str, Any]] = {}
    for row in rows:
        category = categories.get(row.category_id) if row.category_id else None
        result[row.id] = {
            "id": row.id,
            "account_id": row.account_id,
            "posted_date": row.posted_date,
            "transaction_date": row.transaction_date,
            "amount": str(row.amount),
            "currency": row.currency,
            "raw_description": row.raw_description,
            "description": row.description,
            "raw_type": row.raw_type,
            "provider_transaction_id": row.provider_transaction_id,
            "source_label": row.source_label,
            "classification": row.classification,
            "category_id": row.category_id,
            "category_slug": category.slug if category else None,
            "category_name": category.display_name if category else None,
            "category_source": row.category_source,
            "revision": row.revision,
            "split_count": split_counts.get(row.id, 0),
            "transfer_match_id": transfer_ids.get(row.id),
        }
    return result


def _transaction_read(session: Session, row: FinancialTransaction) -> dict[str, Any]:
    return _transaction_reads(session, [row])[row.id]


def list_transactions(
    session: Session,
    *,
    account_id: UUID | None,
    start_date: date | None,
    end_date: date | None,
    limit: int,
    offset: int = 0,
) -> list[dict[str, Any]]:
    query = select(FinancialTransaction).where(
        FinancialTransaction.status == "published"
    )
    if account_id:
        query = query.where(FinancialTransaction.account_id == account_id)
    if start_date:
        query = query.where(FinancialTransaction.posted_date >= start_date)
    if end_date:
        query = query.where(FinancialTransaction.posted_date <= end_date)
    rows = list(
        session.scalars(
            query.order_by(
                FinancialTransaction.posted_date.desc(), FinancialTransaction.id
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return list(_transaction_reads(session, rows).values())


def create_manual_transaction(
    session: Session, data: TransactionManualCreate
) -> FinancialTransaction:
    existing = session.scalar(
        select(FinancialTransaction).where(
            FinancialTransaction.idempotency_key == data.idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.account_id != data.account_id
            or existing.amount != Decimal(data.amount)
            or existing.posted_date != data.posted_date
            or existing.transaction_date != data.transaction_date
            or existing.currency != data.currency
            or existing.description != data.description
            or existing.classification != data.classification
            or existing.category_id != data.category_id
        ):
            raise TransactionConflict(
                "Idempotency key was used for another transaction."
            )
        return existing
    account = session.get(Account, data.account_id)
    if account is None or not account.active:
        raise TransactionNotFound("Active account not found.")
    category = (
        session.get(SpendingCategory, data.category_id) if data.category_id else None
    )
    if data.category_id and category is None:
        raise TransactionNotFound("Category not found.")
    value = Decimal(data.amount)
    if value == 0:
        raise TransactionError("Transaction amount cannot be zero.")
    merchant = normalize_merchant(data.description)
    now = utc_now()
    row = FinancialTransaction(
        id=uuid4(),
        account_id=data.account_id,
        source_label="manual",
        posted_date=data.posted_date,
        transaction_date=data.transaction_date,
        amount=value,
        currency=data.currency,
        raw_posted_date=data.posted_date.isoformat(),
        raw_transaction_date=data.transaction_date.isoformat()
        if data.transaction_date
        else None,
        raw_amount=data.amount,
        raw_currency=data.currency,
        raw_description=data.description,
        description=data.description,
        normalized_merchant=merchant,
        raw_type=None,
        raw_payload={"manual": True},
        fingerprint=_fingerprint(
            data.account_id, data.posted_date, value, data.currency, merchant
        ),
        status="published",
        identity_resolution="manual",
        classification=data.classification,
        category_id=data.category_id,
        category_source="user" if category else "unclassified",
        revision=1,
        idempotency_key=data.idempotency_key,
        diagnostics={"source": "manual"},
        published_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    _event(
        session,
        row,
        action="manual_create",
        reason="Manual transaction entry",
        before={},
        after={"amount": data.amount, "date": data.posted_date.isoformat()},
    )
    return row


def patch_transaction(
    session: Session, transaction_id: UUID, data: TransactionPatch
) -> FinancialTransaction:
    row = session.get(FinancialTransaction, transaction_id)
    if row is None or row.status != "published":
        raise TransactionNotFound("Published transaction not found.")
    if row.revision != data.expected_revision:
        raise TransactionConflict("Transaction changed; reload before editing.")
    _advance_revision(
        session,
        FinancialTransaction,
        row.id,
        expected=data.expected_revision,
        extra=(FinancialTransaction.status == "published",),
    )
    before = {
        "classification": row.classification,
        "category_id": str(row.category_id) if row.category_id else None,
    }
    changes = data.model_dump(
        exclude={"expected_revision", "reason"}, exclude_unset=True
    )
    if "classification" in changes and changes["classification"] is not None:
        row.classification = changes["classification"]
    if "category_id" in changes:
        category_id = changes["category_id"]
        if (
            category_id is not None
            and session.get(SpendingCategory, category_id) is None
        ):
            raise TransactionNotFound("Category not found.")
        row.category_id = category_id
        row.category_source = "user" if category_id else "unclassified"
    row.revision += 1
    row.updated_at = utc_now()
    _event(
        session,
        row,
        action="classify",
        reason=data.reason,
        before=before,
        after={
            "classification": row.classification,
            "category_id": str(row.category_id) if row.category_id else None,
        },
    )
    session.flush()
    return row


def replace_splits(
    session: Session, transaction_id: UUID, data: TransactionSplitsReplace
) -> list[TransactionSplit]:
    row = session.get(FinancialTransaction, transaction_id)
    if row is None or row.status != "published" or row.amount is None:
        raise TransactionNotFound("Published transaction not found.")
    if row.revision != data.expected_revision:
        raise TransactionConflict("Transaction changed; reload before editing splits.")
    amounts = [Decimal(split.amount) for split in data.splits]
    if amounts and sum(amounts, Decimal(0)) != row.amount:
        raise TransactionError(
            "Split amounts must add exactly to the signed transaction amount."
        )
    for item in data.splits:
        if item.category_id and session.get(SpendingCategory, item.category_id) is None:
            raise TransactionNotFound("Split category not found.")
    _advance_revision(
        session,
        FinancialTransaction,
        row.id,
        expected=data.expected_revision,
        extra=(FinancialTransaction.status == "published",),
    )
    old = list(
        session.scalars(
            select(TransactionSplit).where(TransactionSplit.transaction_id == row.id)
        )
    )
    before = [
        {
            "amount": str(item.amount),
            "category_id": str(item.category_id) if item.category_id else None,
        }
        for item in old
    ]
    for split_row in old:
        session.delete(split_row)
    # Free (transaction_id, split_index) uniqueness before replacement inserts.
    session.flush()
    row.revision += 1
    row.updated_at = utc_now()
    created = [
        TransactionSplit(
            id=uuid4(),
            transaction_id=row.id,
            split_index=index,
            amount=amount,
            category_id=item.category_id,
            note=item.note,
            revision=row.revision,
        )
        for index, (item, amount) in enumerate(zip(data.splits, amounts, strict=True))
    ]
    session.add_all(created)
    _event(
        session,
        row,
        action="split",
        reason=data.reason,
        before={"splits": before},
        after={
            "splits": [
                {
                    "amount": str(item.amount),
                    "category_id": str(item.category_id) if item.category_id else None,
                }
                for item in created
            ]
        },
    )
    session.flush()
    return created


def list_categories(session: Session) -> list[SpendingCategory]:
    return list(
        session.scalars(
            select(SpendingCategory).order_by(
                SpendingCategory.display_name, SpendingCategory.id
            )
        )
    )


def list_category_rules(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(MerchantCategoryRule)
        .where(MerchantCategoryRule.active.is_(True))
        .order_by(
            MerchantCategoryRule.priority, MerchantCategoryRule.normalized_merchant
        )
        .limit(500)
    )
    return [
        {
            "id": row.id,
            "merchant": row.normalized_merchant,
            "normalized_merchant": row.normalized_merchant,
            "category_id": row.category_id,
            "priority": row.priority,
            "version": row.version,
            "active": row.active,
        }
        for row in rows
    ]


def transfer_candidates(session: Session, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(FinancialTransaction)
            .where(
                FinancialTransaction.status == "published",
                FinancialTransaction.posted_date.is_not(None),
                FinancialTransaction.amount.is_not(None),
            )
            .order_by(FinancialTransaction.posted_date.desc())
            .limit(500)
        )
    )
    linked_ids = set(session.scalars(select(ActiveTransferTransaction.transaction_id)))
    display_rows = _transaction_reads(session, rows)
    result: list[dict[str, Any]] = []
    for index, first in enumerate(rows):
        if first.id in linked_ids or first.amount is None or first.posted_date is None:
            continue
        for second in rows[index + 1 :]:
            if (
                second.id in linked_ids
                or second.amount is None
                or second.posted_date is None
            ):
                continue
            if (
                first.account_id == second.account_id
                or first.currency != second.currency
            ):
                continue
            gap = abs((first.posted_date - second.posted_date).days)
            if gap > 3 or first.amount == 0 or first.amount != -second.amount:
                continue
            result.append(
                {
                    "first_transaction": display_rows[first.id],
                    "second_transaction": display_rows[second.id],
                    "date_gap_days": gap,
                    "reason": (
                        "Opposite signed amounts match across accounts "
                        "within three days."
                    ),
                }
            )
            if len(result) >= limit:
                return result
    return result


def confirm_transfer(session: Session, data: TransferCreate) -> TransferMatch:
    if data.first_transaction_id == data.second_transaction_id:
        raise TransactionError("A transfer needs two different transactions.")
    left = session.get(FinancialTransaction, data.first_transaction_id)
    right = session.get(FinancialTransaction, data.second_transaction_id)
    if (
        left is None
        or right is None
        or left.status != "published"
        or right.status != "published"
    ):
        raise TransactionNotFound("Both transfer transactions must be published.")
    if (
        left.account_id == right.account_id
        or left.currency != right.currency
        or left.amount is None
        or right.amount is None
        or left.amount != -right.amount
        or left.posted_date is None
        or right.posted_date is None
        or abs((left.posted_date - right.posted_date).days) > 3
    ):
        raise TransactionError(
            "Transfer rows need equal opposite amounts and currency, with dates within "
            "three days."
        )
    existing = session.scalar(
        select(ActiveTransferTransaction.transaction_id).where(
            ActiveTransferTransaction.transaction_id.in_([left.id, right.id])
        )
    )
    if existing is not None:
        raise TransactionConflict("One of these transactions is already linked.")
    first_id, second_id = sorted((left.id, right.id), key=str)
    now = utc_now()
    match = TransferMatch(
        id=uuid4(),
        first_transaction_id=first_id,
        second_transaction_id=second_id,
        status="confirmed",
        match_method="user_confirmed",
        reason=data.reason,
        confirmed_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(match)
    session.add_all(
        [
            ActiveTransferTransaction(transaction_id=first_id, transfer_id=match.id),
            ActiveTransferTransaction(transaction_id=second_id, transfer_id=match.id),
        ]
    )
    for transaction in (left, right):
        _advance_revision(
            session,
            FinancialTransaction,
            transaction.id,
            expected=transaction.revision,
            extra=(FinancialTransaction.status == "published",),
        )
        before = {"transfer_match_id": None}
        transaction.revision += 1
        transaction.updated_at = now
        _event(
            session,
            transaction,
            action="transfer_link",
            reason=data.reason,
            before=before,
            after={"transfer_match_id": str(match.id)},
        )
    session.flush()
    return match


def unlink_transfer(session: Session, transfer_id: UUID, reason: str) -> TransferMatch:
    match = session.get(TransferMatch, transfer_id)
    if match is None:
        raise TransactionNotFound("Transfer link not found.")
    if match.status != "confirmed":
        raise TransactionConflict("Transfer link is not active.")
    claims = list(
        session.scalars(
            select(ActiveTransferTransaction).where(
                ActiveTransferTransaction.transfer_id == match.id
            )
        )
    )
    transactions = [
        session.get(FinancialTransaction, transaction_id)
        for transaction_id in (match.first_transaction_id, match.second_transaction_id)
    ]
    for transaction in transactions:
        if transaction is not None:
            _advance_revision(
                session,
                FinancialTransaction,
                transaction.id,
                expected=transaction.revision,
                extra=(FinancialTransaction.status == "published",),
            )
    match.status = "unlinked"
    match.reason = reason
    match.updated_at = utc_now()
    for claim in claims:
        session.delete(claim)
    for transaction in transactions:
        if transaction:
            transaction.revision += 1
            transaction.updated_at = utc_now()
            _event(
                session,
                transaction,
                action="transfer_unlink",
                reason=reason,
                before={
                    "transfer_match_id": str(match.id),
                    "first_transaction_id": str(match.first_transaction_id),
                    "second_transaction_id": str(match.second_transaction_id),
                },
                after={"transfer_match_id": None},
            )
    session.flush()
    return match


def read_splits(session: Session, transaction_id: UUID) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(TransactionSplit)
        .where(TransactionSplit.transaction_id == transaction_id)
        .order_by(TransactionSplit.split_index)
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        category = (
            session.get(SpendingCategory, row.category_id) if row.category_id else None
        )
        result.append(
            {
                "id": row.id,
                "split_index": row.split_index,
                "amount": str(row.amount),
                "category_id": row.category_id,
                "category_slug": category.slug if category else None,
                "category_name": category.display_name if category else None,
                "note": row.note,
            }
        )
    return result
