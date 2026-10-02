"""Reviewed, bounded fund composition publication shared by every file format."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from functools import partial
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    FundLine,
    FundSnapshot,
    ImportAttempt,
    ImportBatch,
    ImportReviewEvent,
    ImportRow,
    Security,
    SecurityIdentifier,
    utc_now,
)
from app.db.transactions import run_database_unit
from app.domains import imports
from app.providers.fund_formats import ParsedFund, parse_fund, weight
from app.storage.file_store import PrivateFileStore


def classify(raw: str) -> str:
    value = raw.casefold().strip()
    return {
        "equity": "equity",
        "stock": "equity",
        "cash": "cash",
        "cash and/or derivatives": "unsupported",
        "money market": "cash",
        "etf": "nested",
        "fund": "nested",
        "futures": "unsupported",
        "derivative": "unsupported",
        "swap": "unsupported",
    }.get(value, "other")


def match(
    session: Session, payload: dict[str, str], parsed: ParsedFund
) -> Security | None:
    candidates: set[UUID] = set()
    for field in ("cusip", "isin"):
        raw = payload.get(parsed.mapping.get(field, ""), "").strip()
        if raw and raw != "-":
            found = set(
                session.scalars(
                    select(SecurityIdentifier.security_id).where(
                        SecurityIdentifier.namespace == field,
                        SecurityIdentifier.normalized_value == raw.upper(),
                        SecurityIdentifier.review_status == "reviewed",
                        SecurityIdentifier.valid_from <= parsed.as_of,
                        (
                            SecurityIdentifier.valid_to.is_(None)
                            | (SecurityIdentifier.valid_to >= parsed.as_of)
                        ),
                    )
                )
            )
            if found:
                candidates |= found
    identifier = payload.get(parsed.mapping.get("identifier", ""), "").strip().upper()
    if identifier and identifier != "-":
        found = set(
            session.scalars(
                select(Security.id).where(Security.display_ticker == identifier)
            )
        )
        if candidates and found and candidates != found:
            return None
        candidates |= found
    return (
        session.get(Security, next(iter(candidates))) if len(candidates) == 1 else None
    )


def preview(
    factory: sessionmaker[Session],
    store: PrivateFileStore,
    *,
    content: bytes,
    filename: str,
    fund_id: UUID,
    as_of: date,
    source: str,
    format_id: str,
    unit: str,
    mapping: dict[str, str],
    key: str,
    max_rows: int,
) -> tuple[UUID, bool]:
    if (
        as_of > utc_now().date()
        or not source.strip()
        or len(source) > 100
        or not 1 <= len(key) <= 128
    ):
        raise imports.InvalidCsv(
            "Confirm a past/current date, source and idempotency key"
        )
    with factory() as session:
        fund = session.get(Security, fund_id)
        if fund is None or fund.security_type != "etf":
            raise imports.ImportNotFound("Select an ETF security")
        ticker = fund.display_ticker or ""
    parsed = parse_fund(
        content,
        format_id=format_id,
        ticker=ticker,
        as_of=as_of,
        mapping=mapping,
        weight_unit=unit,
        max_rows=max_rows,
    )
    storage_key, digest = store.put(content)
    identity = imports._canonical_hash(
        ["fund", str(fund_id), as_of.isoformat(), source, digest]
    )
    interpretation = imports._canonical_hash(
        [parsed.parser_version, parsed.mapping, parsed.weight_unit]
    )
    payload_hash = imports._canonical_hash([identity, interpretation])
    new_id = uuid4()
    batches = imports._batch_rows(parsed.rows)

    def begin(session: Session) -> tuple[UUID, bool]:
        prior_key = session.scalar(
            select(ImportAttempt).where(ImportAttempt.idempotency_key == key)
        )
        if prior_key:
            if prior_key.payload_hash != payload_hash:
                raise imports.ImportConflict(
                    "Idempotency key already used with another payload"
                )
            return prior_key.id, prior_key.status == "published"
        prior = session.scalar(
            select(ImportAttempt)
            .where(
                ImportAttempt.identity_hash == identity,
                ImportAttempt.interpretation_hash == interpretation,
                ImportAttempt.status.not_in(("cancelled", "replaced")),
            )
            .order_by(ImportAttempt.created_at.desc())
        )
        if prior:
            return prior.id, True
        file = imports._new_file(
            session,
            key=storage_key,
            digest=digest,
            filename=imports._source_filename(filename),
            size=len(content),
        )
        session.add(
            ImportAttempt(
                id=new_id,
                file_id=file.id,
                kind="fund",
                account_id=None,
                fund_security_id=fund_id,
                effective_date=as_of,
                source_label=source,
                parser_version=parsed.parser_version,
                column_mapping=parsed.mapping,
                file_sha256=digest,
                identity_hash=identity,
                interpretation_hash=interpretation,
                payload_hash=payload_hash,
                status="staging",
                review_revision=1,
                expected_account_revision=None,
                idempotency_key=key,
                row_count=len(parsed.rows),
                batch_count=len(batches),
                diagnostics={
                    "weight_unit": parsed.weight_unit,
                    "source_url": parsed.source_url or "",
                    "source_quality": "user_provided",
                    "format": format_id,
                },
            )
        )
        session.add(
            ImportReviewEvent(
                id=uuid4(),
                import_id=new_id,
                review_revision=1,
                action="preview",
                reason="Fund composition requires explicit acceptance",
                change_payload={"rows": len(parsed.rows)},
            )
        )
        return new_id, False

    try:
        import_id, duplicate = run_database_unit(factory, begin)
    except IntegrityError as exc:
        raise imports.ImportConflict(
            "Concurrent import; retry with the same key"
        ) from exc
    with factory() as session:
        attempt = session.get(ImportAttempt, import_id)
        if duplicate and attempt and attempt.status != "staging":
            return import_id, True
    offset = 2
    for ordinal, batch in enumerate(batches):

        def stage(
            session: Session, items: list[dict[str, str]], index: int, start: int
        ) -> None:
            advanced = session.execute(
                update(ImportAttempt)
                .where(
                    ImportAttempt.id == import_id,
                    ImportAttempt.status == "staging",
                    ImportAttempt.review_revision == 1,
                )
                .values(updated_at=utc_now())
            )
            if getattr(advanced, "rowcount", 0) != 1:
                raise imports.ImportRevisionConflict
            marker_id = uuid5(import_id, f"preview:{index}")
            if session.get(ImportBatch, marker_id):
                return
            for number, payload in enumerate(items, start):
                raw_weight = payload.get(parsed.mapping["weight"], "")
                raw_class = payload.get(
                    parsed.mapping.get("asset_type", ""),
                    payload.get(
                        "__class", "equity" if format_id == "spdr" else "other"
                    ),
                )
                security = match(session, payload, parsed)
                try:
                    normalized = weight(raw_weight, parsed.weight_unit)
                    state, diagnostics = "ready", {}
                except ValueError as exc:
                    normalized, state, diagnostics = (
                        None,
                        "invalid",
                        {"weight": str(exc)},
                    )
                session.add(
                    ImportRow(
                        id=uuid5(import_id, f"row:{number}"),
                        import_id=import_id,
                        row_number=number,
                        raw_payload=payload,
                        raw_identifier=payload.get(
                            parsed.mapping.get("identifier", "")
                        ),
                        raw_name=payload.get(parsed.mapping.get("name", "")),
                        raw_asset_type=raw_class,
                        raw_weight_value=raw_weight,
                        raw_weight_unit=parsed.weight_unit,
                        security_id=security.id if security else None,
                        normalized_weight=normalized,
                        row_status=state,
                        excluded=False,
                        diagnostics=diagnostics,
                    )
                )
            session.add(
                ImportBatch(
                    id=marker_id,
                    import_id=import_id,
                    purpose="preview",
                    review_revision=1,
                    ordinal=index,
                    payload_hash=imports._canonical_hash(items),
                    row_count=len(items),
                    status="complete",
                )
            )

        run_database_unit(
            factory, partial(stage, items=batch, index=ordinal, start=offset)
        )
        offset += len(batch)

    def finish(session: Session) -> None:
        session.execute(
            update(ImportAttempt)
            .where(
                ImportAttempt.id == import_id,
                ImportAttempt.status == "staging",
                ImportAttempt.review_revision == 1,
            )
            .values(status="review")
        )

    run_database_unit(factory, finish)
    return import_id, duplicate


def correct(
    session: Session,
    import_id: UUID,
    row_id: UUID,
    *,
    revision: int,
    reason: str,
    security_id: UUID | None,
    weight_value: str | None,
    asset_type: str | None,
) -> dict[str, Any]:
    attempt = session.get(ImportAttempt, import_id)
    row = session.get(ImportRow, row_id)
    if not attempt or attempt.kind != "fund" or not row or row.import_id != import_id:
        raise imports.ImportNotFound
    result = session.execute(
        update(ImportAttempt)
        .where(
            ImportAttempt.id == import_id,
            ImportAttempt.status == "review",
            ImportAttempt.review_revision == revision,
        )
        .values(review_revision=revision + 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise imports.ImportRevisionConflict
    before = {
        "security_id": str(row.security_id),
        "weight": str(row.normalized_weight),
        "class": row.diagnostics.get("reviewed_class"),
    }
    if security_id is not None:
        if session.get(Security, security_id) is None:
            raise imports.ImportNotFound("Security not found")
        row.security_id = security_id
    if weight_value is not None:
        try:
            row.normalized_weight = weight(weight_value, "decimal")
        except ValueError as exc:
            raise imports.ImportBlocked(str(exc)) from exc
    if asset_type is not None:
        row.diagnostics = {**row.diagnostics, "reviewed_class": asset_type}
    row.row_status = "ready" if row.normalized_weight is not None else "invalid"
    row.correction_reason = reason
    attempt.review_revision = revision + 1
    session.add(
        ImportReviewEvent(
            id=uuid4(),
            import_id=import_id,
            review_revision=revision + 1,
            action="correct_row",
            reason=reason,
            change_payload={
                "before": before,
                "row": row.row_number,
                "security_id": str(row.security_id),
                "weight": str(row.normalized_weight),
            },
        )
    )
    return imports._row_read(session, row)


def publish(factory: sessionmaker[Session], import_id: UUID, revision: int) -> UUID:
    snapshot_id = uuid5(import_id, f"fund:{revision}")
    with factory() as session:
        attempt = session.get(ImportAttempt, import_id)
        if not attempt or attempt.kind != "fund":
            raise imports.ImportNotFound
        existing = session.scalar(
            select(FundSnapshot).where(
                FundSnapshot.import_id == import_id, FundSnapshot.status == "published"
            )
        )
        if existing:
            return existing.id
        if attempt.review_revision != revision or attempt.status not in {
            "review",
            "publishing",
        }:
            raise imports.ImportRevisionConflict
        rows = imports._import_rows(session, import_id)
        if len(rows) != attempt.row_count or any(
            r.normalized_weight is None or r.excluded for r in rows
        ):
            raise imports.ImportBlocked(
                "Correct every invalid weight; raw fund rows cannot be dropped"
            )
        values = [
            (
                r.row_number,
                r.id,
                r.security_id,
                r.normalized_weight,
                str(
                    r.diagnostics.get("reviewed_class")
                    or classify(r.raw_asset_type or "other")
                ),
                r.raw_identifier,
                r.raw_name,
            )
            for r in rows
        ]
        with localcontext() as context:
            context.prec = 80
            total = sum((r.normalized_weight or Decimal(0) for r in rows), Decimal(0))
            recognized = sum(
                (
                    r.normalized_weight or Decimal(0)
                    for r in rows
                    if r.security_id
                    and (
                        r.diagnostics.get("reviewed_class")
                        or classify(r.raw_asset_type or "other")
                    )
                    == "equity"
                    and (matched := session.get(Security, r.security_id)) is not None
                    and matched.security_type == "equity"
                ),
                Decimal(0),
            )
        if abs(total) >= Decimal("1e8"):
            raise imports.ImportBlocked("Aggregate weights exceed supported precision")
        warnings: list[str] = []
        if total > 1 or any(
            (v[3] or Decimal(0)) < 0 or v[4] == "unsupported" for v in values
        ):
            warnings.append("unsupported_signed_leverage_or_overweight")
        identities = [v[2] or (v[5], v[6]) for v in values if v[4] != "cash"]
        if len(set(identities)) != len(identities):
            warnings.append("duplicate_economic_lines")
        quality = (
            "opaque"
            if warnings
            else "partial"
            if total < 1 or recognized < total
            else "complete"
        )
        fund_id, source, source_url, version, digest, as_of, fetched = (
            attempt.fund_security_id,
            attempt.source_label,
            attempt.diagnostics.get("source_url"),
            attempt.parser_version,
            attempt.file_sha256,
            attempt.effective_date,
            attempt.created_at,
        )
    batches = [
        values[i : i + imports.IMPORT_BATCH_ROWS]
        for i in range(0, len(values), imports.IMPORT_BATCH_ROWS)
    ]
    for ordinal, batch in enumerate(batches):

        def stage(session: Session, index: int, items: list[Any]) -> None:
            changed = session.execute(
                update(ImportAttempt)
                .where(
                    ImportAttempt.id == import_id,
                    ImportAttempt.review_revision == revision,
                    ImportAttempt.status.in_(("review", "publishing")),
                )
                .values(status="publishing", updated_at=utc_now())
                .execution_options(synchronize_session=False)
            )
            if getattr(changed, "rowcount", 0) != 1:
                raise imports.ImportRevisionConflict
            if session.get(FundSnapshot, snapshot_id) is None:
                session.add(
                    FundSnapshot(
                        id=snapshot_id,
                        fund_security_id=fund_id,
                        import_id=import_id,
                        review_revision=revision,
                        as_of=as_of,
                        fetched_at=fetched,
                        source=source,
                        source_url=source_url or None,
                        parser_version=version,
                        content_hash=digest,
                        status="staging",
                        reported_weight=total,
                        recognized_weight=recognized,
                        quality_status=quality,
                        diagnostics={
                            "warnings": warnings,
                            "source_quality": "user_provided",
                        },
                    )
                )
                session.flush()
            marker_id = uuid5(import_id, f"fund-publish:{revision}:{index}")
            if session.get(ImportBatch, marker_id):
                return
            for number, row_id, security_id, w, kind, raw_id, name in items:
                session.add(
                    FundLine(
                        id=uuid5(snapshot_id, f"row:{number}"),
                        snapshot_id=snapshot_id,
                        row_number=number,
                        review_row_id=row_id,
                        security_id=security_id,
                        weight=w,
                        asset_type=kind,
                        raw_identifier=raw_id,
                        raw_name=name,
                        match_status="resolved" if security_id else "unresolved",
                    )
                )
            session.add(
                ImportBatch(
                    id=marker_id,
                    import_id=import_id,
                    purpose="fund-publish",
                    review_revision=revision,
                    ordinal=index,
                    payload_hash=imports._canonical_hash(
                        [[str(x) for x in item] for item in items]
                    ),
                    row_count=len(items),
                    status="complete",
                )
            )

        run_database_unit(factory, partial(stage, index=ordinal, items=batch))

    def finalize(session: Session) -> UUID:
        snapshot = session.get(FundSnapshot, snapshot_id)
        if snapshot and snapshot.status == "published":
            return snapshot_id
        count = session.scalar(
            select(func.count(FundLine.id)).where(FundLine.snapshot_id == snapshot_id)
        )
        marker_count = session.scalar(
            select(func.count(ImportBatch.id)).where(
                ImportBatch.import_id == import_id,
                ImportBatch.purpose == "fund-publish",
                ImportBatch.review_revision == revision,
            )
        )
        if count != len(values) or marker_count != len(batches):
            raise imports.ImportBlocked("Publication staging is incomplete")
        changed = session.execute(
            update(ImportAttempt)
            .where(
                ImportAttempt.id == import_id,
                ImportAttempt.review_revision == revision,
                ImportAttempt.status == "publishing",
            )
            .values(status="published", updated_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        if getattr(changed, "rowcount", 0) != 1 or snapshot is None:
            raise imports.ImportRevisionConflict
        snapshot.status = "published"
        snapshot.published_at = utc_now()
        return snapshot_id

    return run_database_unit(factory, finalize)


def snapshot_read(session: Session, snapshot: FundSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "fund_security_id": snapshot.fund_security_id,
        "import_id": snapshot.import_id,
        "as_of": snapshot.as_of,
        "fetched_at": snapshot.fetched_at,
        "source": snapshot.source,
        "source_url": snapshot.source_url,
        "parser_version": snapshot.parser_version,
        "content_hash": snapshot.content_hash,
        "quality_status": snapshot.quality_status,
        "reported_weight": str(snapshot.reported_weight),
        "recognized_weight": str(snapshot.recognized_weight),
        "warnings": snapshot.diagnostics.get("warnings", []),
        "row_count": session.scalar(
            select(func.count(FundLine.id)).where(FundLine.snapshot_id == snapshot.id)
        )
        or 0,
    }
