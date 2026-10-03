from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Account,
    Issuer,
    PositionSnapshot,
    PositionSnapshotLine,
    PrivateFile,
    Security,
)
from app.domains import reports
from app.recovery.archive import (
    RecoveryError,
    _alembic_head,
    _decode_row,
    _decrypt_stream,
    _decrypted_payload,
    _encode_row,
    _encrypt_payload,
    _encrypt_stream,
    _included_tables,
    _json_from_tree,
    _json_tree,
    _schema_fingerprint,
    _table_rows,
    _target_empty,
    _verify_zip,
    export_database,
    restore_archive,
    verify_archive,
)
from app.storage.file_store import PrivateFileStore

PASSPHRASE = "synthetic-only-recovery-passphrase"
SCOPE = "synthetic-personal-scope"
API_ROOT = Path(__file__).resolve().parents[1]


def _read_database_admin_url() -> URL:
    value = os.environ.get("STAGE4_RECOVERY_TEST_ADMIN_URL")
    if not value:
        pytest.skip(
            "Set STAGE4_RECOVERY_TEST_ADMIN_URL to run isolated PostgreSQL drill"
        )
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or (url.host or "").casefold() not in {"localhost", "127.0.0.1", "::1"}
        or url.database != "postgres"
    ):
        pytest.fail("Recovery test admin URL must be loopback /postgres with psycopg")
    return url


def _database_url(admin: URL, database: str) -> str:
    return admin.set(database=database).render_as_string(hide_password=False)


def _create_database(admin: URL, database: str) -> None:
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", pool_size=1)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    finally:
        engine.dispose()


def _drop_database(admin: URL, database: str) -> None:
    if not database.startswith(("pf_source_", "pf_restore_")):
        raise AssertionError("Refusing to drop a non-namespaced recovery test database")
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", pool_size=1)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'
            )
    finally:
        engine.dispose()


def _upgrade_database(database_url: str) -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DATABASE_BACKEND": "postgres",
            "DATABASE_URL": database_url,
        }
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _default_column(column: Any) -> Any:
    if column.nullable:
        return None
    kind = type(column.type).__name__.casefold()
    if kind in {"uuid"}:
        return uuid.uuid4()
    if kind in {"numeric"}:
        return Decimal("1.2300")
    if kind in {"datetime"}:
        return datetime(
            2026, 10, 3, 12, 13, 14, 123456, tzinfo=timezone(timedelta(hours=-7))
        )
    if kind in {"date"}:
        return date(2026, 10, 3)
    if kind in {"json", "jsonb"}:
        return {"$pf": "ordinary-user-key", "items": [1, 1.25, None, True]}
    if kind in {"boolean"}:
        return False
    if kind in {"integer"}:
        return 17
    if kind in {"largebinary"}:
        return b"binary"
    if kind in {"text", "string"}:
        return "synthetic"
    raise AssertionError(f"Add serializer test coverage for {column.type!s}")


def _rewrite_archive(
    source: Path,
    destination: Path,
    transform: Any,
) -> None:
    with _decrypted_payload(source, PASSPHRASE) as (_archive_path, payload):
        with zipfile.ZipFile(payload) as archive:
            members = {item.filename: archive.read(item) for item in archive.infolist()}
        transformed = transform(members)
        with tempfile.TemporaryDirectory(
            prefix="pf-recovery-test-", dir=destination.parent
        ) as temporary:
            root = Path(temporary)
            os.chmod(root, 0o700)
            rewritten = root / "payload.zip"
            with zipfile.ZipFile(
                rewritten, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                for name, data in sorted(transformed.items()):
                    archive.writestr(name, data)
            os.chmod(rewritten, 0o600)
            _encrypt_payload(rewritten, destination, PASSPHRASE)


def test_typed_rows_preserve_decimal_time_uuid_and_json_keys() -> None:
    table = next(table for table in _included_tables() if table.name == "quotes")
    values = {column.name: _default_column(column) for column in table.columns}
    values.update(
        {
            "price": Decimal("123456.7890123400"),
            "as_of": datetime(
                2026, 10, 3, 9, 30, 0, 987654, tzinfo=timezone(timedelta(hours=-7))
            ),
            "provider_metadata": {
                "$pf": {"decimal": "ordinary-key"},
                "precise": 0.1,
                "large_integer": 10**30,
                "nested": [{"$pf": "still-user-data"}],
            },
        }
    )
    decoded = _decode_row(table, json.loads(_encode_row(table, values)))
    assert decoded["price"] == Decimal("123456.7890123400")
    assert decoded["as_of"] == datetime(2026, 10, 3, 16, 30, 0, 987654, tzinfo=UTC)
    assert decoded["provider_metadata"] == values["provider_metadata"]
    assert isinstance(decoded["id"], uuid.UUID)


def test_json_codec_rejects_non_finite_and_preserves_tag_like_keys() -> None:
    value = {"$pf": {"t": "user data"}, "nested": [1, 1.0, None]}
    assert _json_from_tree(_json_tree(value)) == value
    with pytest.raises(RecoveryError, match="Non-finite"):
        _json_tree(float("nan"))


def test_chunked_encryption_rejects_auth_and_framing_failures() -> None:
    import io

    source = (b"synthetic-financial-payload" * 90_000) + b"end"
    encrypted = io.BytesIO()
    _encrypt_stream(io.BytesIO(source), encrypted, PASSPHRASE)
    ciphertext = encrypted.getvalue()
    decrypted = io.BytesIO()
    _decrypt_stream(io.BytesIO(ciphertext), decrypted, PASSPHRASE)
    assert decrypted.getvalue() == source

    with pytest.raises(RecoveryError, match="authentication failed"):
        _decrypt_stream(
            io.BytesIO(ciphertext), io.BytesIO(), "wrong synthetic passphrase"
        )
    tampered = bytearray(ciphertext)
    tampered[64] ^= 0x01
    with pytest.raises(RecoveryError, match="authentication failed"):
        _decrypt_stream(io.BytesIO(tampered), io.BytesIO(), PASSPHRASE)
    with pytest.raises(RecoveryError, match="truncated"):
        _decrypt_stream(io.BytesIO(ciphertext[:-1]), io.BytesIO(), PASSPHRASE)
    with pytest.raises(RecoveryError, match="trailing"):
        _decrypt_stream(io.BytesIO(ciphertext + b"x"), io.BytesIO(), PASSPHRASE)


def test_restore_requires_explicit_loopback_target_and_acknowledgement() -> None:
    with pytest.raises(RecoveryError, match="loopback"):
        restore_archive(
            "/does/not/exist",
            PASSPHRASE,
            target_database_url="postgresql+psycopg://user@db.example/pf_restore_demo",
            target_private_dir="/tmp/pf_restore_demo",
            source_scope_id=SCOPE,
            target_scope_id="local-scope",
            acknowledge_target="pf_restore_demo",
        )


def test_schema_fingerprint_is_current_and_excludes_auth_and_jobs() -> None:
    names = {table.name for table in _included_tables()}
    assert names.isdisjoint(
        {"auth_principals", "auth_sessions", "security_audit_events", "jobs"}
    )
    assert "private_files" in names
    assert "portfolio_calculations" in names
    assert len(_schema_fingerprint()) == 64
    assert _alembic_head() == "0015_stage4_authentication"


def test_encrypted_export_restore_recovery_idempotency_and_golden_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = _read_database_admin_url()
    suffix = uuid.uuid4().hex[:12]
    source_name = f"pf_source_{suffix}"
    target_name = f"pf_restore_{suffix}"
    source_url = _database_url(admin, source_name)
    target_url = _database_url(admin, target_name)
    created: list[str] = []
    try:
        for name in (source_name, target_name):
            _create_database(admin, name)
            created.append(name)
        _upgrade_database(source_url)
        _upgrade_database(target_url)
        source_engine = create_engine(source_url, pool_pre_ping=True)
        source_store = PrivateFileStore(tmp_path / f"source-files-{suffix}")
        source_factory = sessionmaker(
            bind=source_engine, class_=Session, expire_on_commit=False
        )
        issuer_id, security_id, account_id, snapshot_id = (
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
            uuid.uuid4(),
        )
        with source_factory.begin() as session:
            session.add(
                Issuer(
                    id=issuer_id,
                    normalized_name="synthetic issuer",
                    display_name="Synthetic Issuer",
                )
            )
            session.add(
                Security(
                    id=security_id,
                    security_type="equity",
                    display_ticker="SYN",
                    name="Synthetic Asset",
                    issuer_id=issuer_id,
                    currency="USD",
                )
            )
            account = Account(
                id=account_id,
                name="Synthetic Brokerage",
                account_type="taxable",
                base_currency="USD",
                active=True,
                current_position_revision=1,
                current_position_snapshot_id=None,
                source_type="manual",
            )
            session.add(account)
            session.flush()
            timestamp = datetime.now(UTC) - timedelta(days=1)
            session.add(
                PositionSnapshot(
                    id=snapshot_id,
                    account_id=account_id,
                    snapshot_at=timestamp,
                    source="synthetic",
                    valuation_source="synthetic price",
                    status="accepted",
                    revision=1,
                    accepted_at=timestamp,
                )
            )
            session.flush()
            account.current_position_snapshot_id = snapshot_id
            session.add(
                PositionSnapshotLine(
                    id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    security_id=security_id,
                    unresolved_ref=None,
                    quantity=Decimal("100.0000000000"),
                    reported_value=Decimal("25000.0000000000"),
                    reported_price=Decimal("250.0000000000"),
                    currency="USD",
                    original_row_ref="synthetic-row-1",
                    source="synthetic",
                    quality_status="reported",
                )
            )
            original = b"SYNTHETIC ORIGINAL STATEMENT; NEVER REAL FINANCIAL DATA"
            original_key, original_hash = source_store.put(original)
            session.add(
                PrivateFile(
                    id=uuid.uuid4(),
                    content_hash=original_hash,
                    storage_key=original_key,
                    original_name="synthetic.csv",
                    content_type="text/csv",
                    byte_size=len(original),
                )
            )
        report = reports.create(
            source_factory,
            source_store,
            account_ids=[account_id],
            as_of=None,
        )
        assert Decimal(report["included_valued_nav"]) == Decimal("25000")
        assert report["reconciled"] is True
        with source_factory() as session:
            expected_report = reports.read(
                session, source_store, uuid.UUID(report["id"])
            )
        source_engine.dispose()

        archive_path = tmp_path / f"synthetic-{suffix}.pfarc"
        export_engine = create_engine(source_url)
        try:
            exported = export_database(
                export_engine,
                source_store,
                archive_path,
                backend="postgres",
                source_scope_id=SCOPE,
                passphrase=PASSPHRASE,
            )
        finally:
            export_engine.dispose()
        verified = verify_archive(archive_path, PASSPHRASE)
        assert verified["archive_sha256"] == exported["archive_sha256"]
        assert verified["object_count"] == 2
        with _decrypted_payload(archive_path, PASSPHRASE) as (_path, payload):
            archive, manifest = _verify_zip(payload)
            try:
                object_digest = next(iter(manifest["objects"]))
            finally:
                archive.close()
        missing_object = tmp_path / f"missing-object-{suffix}.pfarc"
        _rewrite_archive(
            archive_path,
            missing_object,
            lambda members: {
                name: content
                for name, content in members.items()
                if name != f"objects/{object_digest}.blob"
            },
        )
        with pytest.raises(RecoveryError, match="members do not match"):
            verify_archive(missing_object, PASSPHRASE)
        tampered_object = tmp_path / f"tampered-object-{suffix}.pfarc"

        def corrupt_object(members: dict[str, bytes]) -> dict[str, bytes]:
            name = f"objects/{object_digest}.blob"
            members[name] = b"x" + members[name][1:]
            return members

        _rewrite_archive(archive_path, tampered_object, corrupt_object)
        with pytest.raises(RecoveryError, match="object hash or size"):
            verify_archive(tampered_object, PASSPHRASE)
        incompatible = tmp_path / f"incompatible-schema-{suffix}.pfarc"

        def change_schema(members: dict[str, bytes]) -> dict[str, bytes]:
            metadata = json.loads(members["manifest.json"])
            metadata["schema_fingerprint"] = "0" * 64
            members["manifest.json"] = json.dumps(
                metadata, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode()
            return members

        _rewrite_archive(archive_path, incompatible, change_schema)
        with pytest.raises(RecoveryError, match="schema fingerprint"):
            verify_archive(incompatible, PASSPHRASE)

        monkeypatch.delenv("DATABASE_URL", raising=False)
        restore_dir = tmp_path / target_name

        committed_batches = 0

        def interrupt(phase: str) -> None:
            nonlocal committed_batches
            if phase == "after_database_batch":
                committed_batches += 1
                if committed_batches == 2:
                    raise RuntimeError("synthetic interruption between batches")

        with pytest.raises(RuntimeError, match="between batches"):
            restore_archive(
                archive_path,
                PASSPHRASE,
                target_database_url=target_url,
                target_private_dir=restore_dir,
                source_scope_id=SCOPE,
                target_scope_id="synthetic-local-scope",
                acknowledge_target=target_name,
                checkpoint=interrupt,
            )
        assert committed_batches == 2
        interrupted_engine = create_engine(target_url)
        try:
            with interrupted_engine.connect() as connection:
                assert _target_empty(connection) is True
        finally:
            interrupted_engine.dispose()
        result = restore_archive(
            archive_path,
            PASSPHRASE,
            target_database_url=target_url,
            target_private_dir=restore_dir,
            source_scope_id=SCOPE,
            target_scope_id="synthetic-local-scope",
            acknowledge_target=target_name,
        )
        assert result["restored"] is True
        target_engine = create_engine(target_url)
        with _decrypted_payload(archive_path, PASSPHRASE) as (_archive_path, payload):
            archive, manifest = _verify_zip(payload)
            try:
                with target_engine.connect().execution_options(
                    isolation_level="REPEATABLE READ"
                ) as connection:
                    with connection.begin():
                        for table in _included_tables():
                            expected = manifest["tables"][table.name]
                            archived = list(_table_rows(archive, table, expected))
                            stored = list(
                                connection.execute(
                                    select(table).order_by(*table.primary_key.columns)
                                ).mappings()
                            )
                            assert len(stored) == expected["row_count"], table.name
                            differences = []
                            for stored_row, archived_row in zip(
                                stored, archived, strict=True
                            ):
                                difference = {
                                    key: (stored_row[key], archived_row[key])
                                    for key in archived_row
                                    if stored_row[key] != archived_row[key]
                                }
                                if difference:
                                    differences.append(difference)
                            assert differences == [], table.name
                            digest = hashlib.sha256(
                                b"".join(
                                    _encode_row(table, dict(row)) + b"\n"
                                    for row in stored
                                )
                            )
                            assert digest.hexdigest() == expected["sha256"], table.name
            finally:
                archive.close()
        repeated = restore_archive(
            archive_path,
            PASSPHRASE,
            target_database_url=target_url,
            target_private_dir=restore_dir,
            source_scope_id=SCOPE,
            target_scope_id="synthetic-local-scope",
            acknowledge_target=target_name,
        )
        assert repeated["already_restored"] is True
        with pytest.raises(RecoveryError, match="another archive"):
            restore_archive(
                archive_path,
                PASSPHRASE,
                target_database_url=target_url,
                target_private_dir=restore_dir,
                source_scope_id=SCOPE,
                target_scope_id="different-scope",
                acknowledge_target=target_name,
            )
        try:
            target_store = PrivateFileStore(restore_dir)
            assert target_store.read(original_key) == original
            target_factory = sessionmaker(
                bind=target_engine, class_=Session, expire_on_commit=False
            )
            with target_factory() as session:
                restored_report = reports.read(
                    session, target_store, uuid.UUID(report["id"])
                )
                restored_account = session.get(Account, account_id)
                assert restored_account is not None
                assert restored_account.current_position_snapshot_id == snapshot_id
                assert restored_report == expected_report
                assert Decimal(restored_report["included_valued_nav"]) == Decimal(
                    "25000"
                )
                assert restored_report["reconciled"] is True
        finally:
            target_engine.dispose()
    finally:
        for name in reversed(created):
            _drop_database(admin, name)
