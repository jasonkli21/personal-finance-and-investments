"""Versioned encrypted finance archives and guarded local PostgreSQL recovery.

The archive contains only the finance schema and referenced immutable file
objects. Authentication sessions, security audit identities and leased jobs
are deliberately not portable. All archive data, including its manifest, is
inside an authenticated encrypted payload.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import struct
import tempfile
import uuid
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, BinaryIO, cast

from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    Uuid,
    bindparam,
    create_engine,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.schema import Table

from app.db.models import Base, Calculation, PrivateFile
from app.storage.file_store import FileStore, PrivateFileStore

API_ROOT = Path(__file__).resolve().parents[2]
FORMAT_VERSION = 1
_MAGIC = b"PFARCV01"
_HEADER = struct.Struct(">8s16s8sI")
_FRAME_SIZE = struct.Struct(">I")
_CHUNK_BYTES = 1024 * 1024
_MAX_PAYLOAD_BYTES = 256 * 1024 * 1024
_MAX_CIPHERTEXT_BYTES = _MAX_PAYLOAD_BYTES + 8192
_MAX_OBJECT_BYTES = 20_000_000
_MAX_TABLE_ROWS = 500_000
_MAX_TOTAL_ROWS = 1_000_000
_MAX_RECORD_BYTES = 1_000_000
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_EXCLUDED_TABLES = {
    "auth_principals": (
        "Identity is rebound locally; no principal identifiers are copied."
    ),
    "auth_sessions": "Browser sessions are revoked by omission and never restored.",
    "security_audit_events": (
        "Authentication audit identities are not portable finance data."
    ),
    "jobs": "Transient job leases and execution state are not portable.",
}
_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_OBJECT_KEY = re.compile(r"^[0-9a-f]{64}\.blob$")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_KDF_N = 32768
_KDF_R = 8
_KDF_P = 1
_KDF_KEY_BYTES = 32
_CHUNK_KDF = {
    "name": "scrypt",
    "n": _KDF_N,
    "r": _KDF_R,
    "p": _KDF_P,
    "key_bytes": _KDF_KEY_BYTES,
}


class RecoveryError(ValueError):
    """The archive or restore target is unsafe, invalid, or incompatible."""


def _included_tables() -> tuple[Table, ...]:
    return tuple(
        table
        for table in Base.metadata.sorted_tables
        if table.name not in _EXCLUDED_TABLES
    )


def _schema_fingerprint() -> str:
    schema: list[dict[str, Any]] = []
    for table in _included_tables():
        constraints: list[dict[str, Any]] = []
        for constraint in sorted(
            table.constraints,
            key=lambda item: (type(item).__name__, item.name or ""),
        ):
            constraint_details = cast(Any, constraint)
            record: dict[str, Any] = {
                "kind": type(constraint).__name__,
                "name": constraint.name,
                "columns": [column.name for column in constraint_details.columns],
            }
            if getattr(constraint_details, "elements", None):
                record["references"] = [
                    {
                        "table": element.column.table.name,
                        "column": element.column.name,
                        "ondelete": element.ondelete,
                    }
                    for element in constraint_details.elements
                ]
            constraints.append(record)
        schema.append(
            {
                "table": table.name,
                "columns": [
                    {
                        "name": column.name,
                        "type": str(column.type),
                        "nullable": column.nullable,
                        "primary_key": column.primary_key,
                    }
                    for column in table.columns
                ],
                "constraints": constraints,
            }
        )
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _alembic_head() -> str:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RecoveryError("Recovery requires one unambiguous Alembic head")
    return heads[0]


def _postgres_revision(connection: Connection) -> str:
    if not inspect(connection).has_table("alembic_version"):
        raise RecoveryError("Database is missing its Alembic schema version")
    versions: list[str] = list(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    expected = _alembic_head()
    if versions != [expected]:
        raise RecoveryError("Database schema is not at the current Alembic head")
    return expected


def _schema_revision(connection: Connection, backend: str) -> str:
    if backend != "postgres":
        raise RecoveryError("Recovery source backend is unsupported")
    return _postgres_revision(connection)


def _json_tree(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if depth > 64:
        raise RecoveryError("JSON data exceeds the supported nesting depth")
    if value is None:
        return {"t": "null"}
    if isinstance(value, bool):
        return {"t": "bool", "v": value}
    if isinstance(value, int):
        return {"t": "int", "v": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecoveryError("Non-finite JSON numbers are not portable")
        return {"t": "float", "v": value.hex()}
    if isinstance(value, str):
        return {"t": "str", "v": value}
    if isinstance(value, list):
        return {"t": "list", "v": [_json_tree(item, depth=depth + 1) for item in value]}
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {
            "t": "map",
            "v": [
                [key, _json_tree(item, depth=depth + 1)]
                for key, item in sorted(value.items())
            ],
        }
    raise RecoveryError("JSON value contains an unsupported type or key")


def _json_from_tree(value: Any, *, depth: int = 0) -> Any:
    if depth > 64 or not isinstance(value, dict) or set(value) - {"t", "v"}:
        raise RecoveryError("Archive JSON value is malformed")
    kind = value.get("t")
    if kind == "null" and set(value) == {"t"}:
        return None
    if kind == "bool" and isinstance(value.get("v"), bool):
        return value["v"]
    if kind == "int" and isinstance(value.get("v"), str):
        try:
            return int(value["v"])
        except ValueError as exc:
            raise RecoveryError("Archive JSON integer is malformed") from exc
    if kind == "float" and isinstance(value.get("v"), str):
        try:
            number = float.fromhex(value["v"])
        except ValueError as exc:
            raise RecoveryError("Archive JSON float is malformed") from exc
        if not math.isfinite(number):
            raise RecoveryError("Archive JSON float is not finite")
        return number
    if kind == "str" and isinstance(value.get("v"), str):
        return value["v"]
    if kind == "list" and isinstance(value.get("v"), list):
        return [_json_from_tree(item, depth=depth + 1) for item in value["v"]]
    if kind == "map" and isinstance(value.get("v"), list):
        result: dict[str, Any] = {}
        for pair in value["v"]:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not isinstance(pair[0], str)
                or pair[0] in result
            ):
                raise RecoveryError("Archive JSON object is malformed")
            result[pair[0]] = _json_from_tree(pair[1], depth=depth + 1)
        return result
    raise RecoveryError("Archive JSON value has an unknown type")


def _encode_column(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, JSON):
        return {"$pf": "json", "v": _json_tree(value)}
    if isinstance(column_type, Uuid):
        return {"$pf": "uuid", "v": str(value)}
    if isinstance(column_type, Numeric):
        return {"$pf": "decimal", "v": format(value, "f")}
    if isinstance(column_type, DateTime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise RecoveryError("Database timestamps must include a UTC offset")
        return {
            "$pf": "datetime",
            "v": value.astimezone(UTC).isoformat(timespec="microseconds"),
        }
    if isinstance(column_type, Date):
        return {"$pf": "date", "v": value.isoformat()}
    if isinstance(column_type, LargeBinary):
        return {"$pf": "bytes", "v": base64.b64encode(value).decode("ascii")}
    if isinstance(column_type, Boolean):
        return value
    if isinstance(column_type, Integer):
        if isinstance(value, bool):
            raise RecoveryError("Boolean supplied for an integer database column")
        return value
    if isinstance(column_type, (String, Text)):
        return value
    raise RecoveryError(
        f"Archive codec does not support column type {type(column_type).__name__}"
    )


def _decode_column(value: Any, column_type: Any) -> Any:
    if value is None:
        return None
    if isinstance(column_type, JSON):
        if not isinstance(value, dict) or value.get("$pf") != "json":
            raise RecoveryError("Archive JSON column is malformed")
        return _json_from_tree(value.get("v"))
    if isinstance(column_type, Uuid):
        if not isinstance(value, dict) or value.get("$pf") != "uuid":
            raise RecoveryError("Archive UUID column is malformed")
        try:
            return uuid.UUID(value["v"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise RecoveryError("Archive UUID column is malformed") from exc
    if isinstance(column_type, Numeric):
        if not isinstance(value, dict) or value.get("$pf") != "decimal":
            raise RecoveryError("Archive decimal column is malformed")
        try:
            result = Decimal(value["v"])
        except (InvalidOperation, TypeError) as exc:
            raise RecoveryError("Archive decimal column is malformed") from exc
        if not result.is_finite():
            raise RecoveryError("Archive decimal column is not finite")
        return result
    if isinstance(column_type, DateTime):
        if not isinstance(value, dict) or value.get("$pf") != "datetime":
            raise RecoveryError("Archive timestamp column is malformed")
        try:
            timestamp_result = datetime.fromisoformat(value["v"])
        except (ValueError, TypeError) as exc:
            raise RecoveryError("Archive timestamp column is malformed") from exc
        if timestamp_result.tzinfo is None or timestamp_result.utcoffset() is None:
            raise RecoveryError("Archive timestamps must include a UTC offset")
        return timestamp_result.astimezone(UTC)
    if isinstance(column_type, Date):
        if not isinstance(value, dict) or value.get("$pf") != "date":
            raise RecoveryError("Archive date column is malformed")
        try:
            return date.fromisoformat(value["v"])
        except (ValueError, TypeError) as exc:
            raise RecoveryError("Archive date column is malformed") from exc
    if isinstance(column_type, LargeBinary):
        if not isinstance(value, dict) or value.get("$pf") != "bytes":
            raise RecoveryError("Archive binary column is malformed")
        try:
            return base64.b64decode(value["v"], validate=True)
        except (ValueError, TypeError) as exc:
            raise RecoveryError("Archive binary column is malformed") from exc
    if isinstance(column_type, Boolean):
        if not isinstance(value, bool):
            raise RecoveryError("Archive boolean column is malformed")
        return value
    if isinstance(column_type, Integer):
        if not isinstance(value, int) or isinstance(value, bool):
            raise RecoveryError("Archive integer column is malformed")
        return value
    if isinstance(column_type, (String, Text)):
        if not isinstance(value, str):
            raise RecoveryError("Archive text column is malformed")
        return value
    raise RecoveryError(
        f"Archive codec does not support column type {type(column_type).__name__}"
    )


def _encode_row(table: Table, row: Mapping[str, Any]) -> bytes:
    values = [_encode_column(row[column.name], column.type) for column in table.columns]
    return json.dumps(values, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _decode_row(table: Table, encoded: Any) -> dict[str, Any]:
    if not isinstance(encoded, list) or len(encoded) != len(table.columns):
        raise RecoveryError(f"Archive row shape does not match {table.name}")
    return {
        column.name: _decode_column(value, column.type)
        for column, value in zip(table.columns, encoded, strict=True)
    }


def _passphrase_key(passphrase: str, salt: bytes) -> bytes:
    encoded = passphrase.encode("utf-8")
    if len(encoded) < 16 or len(encoded) > 1024:
        raise RecoveryError("Recovery passphrase must be 16–1024 UTF-8 bytes")
    return Scrypt(
        salt=salt,
        length=_KDF_KEY_BYTES,
        n=_KDF_N,
        r=_KDF_R,
        p=_KDF_P,
    ).derive(encoded)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        block = stream.read(remaining)
        if not block:
            raise RecoveryError("Encrypted archive is truncated")
        chunks.append(block)
        remaining -= len(block)
    return b"".join(chunks)


def _frame_nonce(prefix: bytes, sequence: int) -> bytes:
    return prefix + sequence.to_bytes(4, "big")


def _frame_aad(header: bytes, sequence: int, size: int) -> bytes:
    return header + sequence.to_bytes(4, "big") + size.to_bytes(4, "big")


def _encrypt_stream(source: BinaryIO, target: BinaryIO, passphrase: str) -> None:
    salt = secrets.token_bytes(16)
    nonce_prefix = secrets.token_bytes(8)
    header = _HEADER.pack(_MAGIC, salt, nonce_prefix, _CHUNK_BYTES)
    key = _passphrase_key(passphrase, salt)
    cipher = AESGCM(key)
    target.write(header)
    sequence = 0
    total = 0
    while block := source.read(_CHUNK_BYTES):
        total += len(block)
        if total > _MAX_PAYLOAD_BYTES or sequence >= 2**32 - 1:
            raise RecoveryError("Archive payload exceeds its configured bound")
        aad = _frame_aad(header, sequence, len(block))
        encrypted = cipher.encrypt(_frame_nonce(nonce_prefix, sequence), block, aad)
        target.write(_FRAME_SIZE.pack(len(block)))
        target.write(encrypted)
        sequence += 1
    aad = _frame_aad(header, sequence, 0)
    target.write(_FRAME_SIZE.pack(0))
    target.write(cipher.encrypt(_frame_nonce(nonce_prefix, sequence), b"", aad))


def _decrypt_stream(source: BinaryIO, target: BinaryIO, passphrase: str) -> int:
    header = _read_exact(source, _HEADER.size)
    magic, salt, nonce_prefix, chunk_size = _HEADER.unpack(header)
    if magic != _MAGIC or chunk_size != _CHUNK_BYTES:
        raise RecoveryError("Encrypted archive format is unsupported")
    cipher = AESGCM(_passphrase_key(passphrase, salt))
    sequence = 0
    total = 0
    while True:
        size = _FRAME_SIZE.unpack(_read_exact(source, _FRAME_SIZE.size))[0]
        if size > _CHUNK_BYTES:
            raise RecoveryError("Encrypted archive frame exceeds its size limit")
        encrypted = _read_exact(source, size + 16)
        try:
            block = cipher.decrypt(
                _frame_nonce(nonce_prefix, sequence),
                encrypted,
                _frame_aad(header, sequence, size),
            )
        except InvalidTag as exc:
            raise RecoveryError(
                "Archive authentication failed (wrong passphrase or tampered bytes)"
            ) from exc
        if size == 0:
            if source.read(1):
                raise RecoveryError("Encrypted archive has trailing data")
            break
        total += len(block)
        if total > _MAX_PAYLOAD_BYTES or sequence >= 2**32 - 1:
            raise RecoveryError("Encrypted archive exceeds its configured bound")
        target.write(block)
        sequence += 1
    return total


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _encrypt_payload(payload: Path, destination: Path, passphrase: str) -> None:
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise RecoveryError("Archive destination already exists")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise RecoveryError("Archive destination parent must be an existing directory")
    temporary = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    linked = False
    try:
        with payload.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            _encrypt_stream(source, target, passphrase)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, destination)
        linked = True
        temporary.unlink()
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        if linked:
            destination.unlink(missing_ok=True)
        raise


@contextmanager
def _decrypted_payload(archive: Path, passphrase: str) -> Iterator[tuple[Path, Path]]:
    archive = archive.absolute()
    if archive.is_symlink() or not archive.is_file():
        raise RecoveryError("Archive must be a regular non-symbolic-link file")
    size = archive.stat().st_size
    if size < _HEADER.size + _FRAME_SIZE.size + 16 or size > _MAX_CIPHERTEXT_BYTES:
        raise RecoveryError("Encrypted archive size is outside the supported bounds")
    with tempfile.TemporaryDirectory(prefix="pf-recovery-") as temporary_directory:
        root = Path(temporary_directory)
        os.chmod(root, 0o700)
        payload = root / "payload.zip"
        try:
            with archive.open("rb") as source, payload.open("xb") as target:
                os.chmod(payload, 0o600)
                _decrypt_stream(source, target, passphrase)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            payload.unlink(missing_ok=True)
            raise
        yield archive, payload


def _lineage_manifest() -> dict[str, dict[str, list[dict[str, str]]]]:
    result: dict[str, dict[str, list[dict[str, str]]]] = {}
    for table in _included_tables():
        references: dict[str, list[dict[str, str]]] = defaultdict(list)
        for constraint in table.foreign_key_constraints:
            for element in constraint.elements:
                references[element.parent.name].append(
                    {
                        "table": element.column.table.name,
                        "column": element.column.name,
                    }
                )
        if references:
            result[table.name] = {
                key: sorted(values, key=lambda item: (item["table"], item["column"]))
                for key, values in sorted(references.items())
            }
    return result


def _snapshot_revisions(
    table_name: str, row: Mapping[str, Any], frozen: dict[str, Any]
) -> None:
    if table_name == "accounts":
        frozen["account_positions"].append(
            {
                "account_id": str(row["id"]),
                "position_revision": row["current_position_revision"],
                "snapshot_id": (
                    str(row["current_position_snapshot_id"])
                    if row["current_position_snapshot_id"] is not None
                    else None
                ),
            }
        )
    elif table_name == "fund_snapshots" and row["status"] == "published":
        frozen["fund_snapshots"].append(
            {
                "snapshot_id": str(row["id"]),
                "import_id": str(row["import_id"]),
                "review_revision": row["review_revision"],
            }
        )
    elif table_name == "transaction_imports" and row["status"] == "published":
        frozen["transaction_imports"].append(
            {"import_id": str(row["id"]), "review_revision": row["review_revision"]}
        )
    elif table_name == "financial_transactions" and row["status"] == "published":
        frozen["transactions"].append(
            {"transaction_id": str(row["id"]), "revision": row["revision"]}
        )
    elif table_name == "tax_lots":
        frozen["tax_lots"].append(
            {"tax_lot_id": str(row["id"]), "state_revision": row["state_revision"]}
        )


def _object_reference(
    references: dict[str, dict[str, Any]],
    *,
    key: Any,
    digest: Any,
    size: Any,
    role: str,
) -> None:
    if (
        not isinstance(key, str)
        or not _OBJECT_KEY.fullmatch(key)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or key != f"{digest}.blob"
    ):
        raise RecoveryError("Stored file key and SHA-256 identity do not match")
    if size is not None and (
        not isinstance(size, int) or not 0 <= size <= _MAX_OBJECT_BYTES
    ):
        raise RecoveryError("Stored file exceeds the portable object size limit")
    entry = references.setdefault(
        digest, {"byte_size": size, "roles": defaultdict(int)}
    )
    if (
        entry["byte_size"] is not None
        and size is not None
        and entry["byte_size"] != size
    ):
        raise RecoveryError("One content hash has inconsistent file sizes")
    if entry["byte_size"] is None:
        entry["byte_size"] = size
    entry["roles"][role] += 1


def export_database(
    engine: Engine,
    file_store: FileStore,
    destination: str | Path,
    *,
    backend: str,
    source_scope_id: str,
    passphrase: str,
) -> dict[str, Any]:
    """Create an encrypted snapshot export without modifying source records."""
    if not _SCOPE.fullmatch(source_scope_id):
        raise RecoveryError("A valid explicit source scope ID is required")
    _passphrase_key(passphrase, b"\0" * 16)
    destination_path = Path(destination).absolute()
    if destination_path.exists() or destination_path.is_symlink():
        raise RecoveryError("Archive destination already exists")
    if not destination_path.parent.is_dir() or destination_path.parent.is_symlink():
        raise RecoveryError("Archive destination parent must be an existing directory")

    with tempfile.TemporaryDirectory(prefix="pf-recovery-export-") as temporary:
        root = Path(temporary)
        os.chmod(root, 0o700)
        record_root = root / "records"
        object_root = root / "objects"
        record_root.mkdir(mode=0o700)
        object_root.mkdir(mode=0o700)
        tables: dict[str, dict[str, Any]] = {}
        file_references: dict[str, dict[str, Any]] = {}
        total_rows = 0
        total_plaintext = 0
        frozen: dict[str, list[dict[str, Any]]] = {
            "account_positions": [],
            "fund_snapshots": [],
            "transaction_imports": [],
            "transactions": [],
            "tax_lots": [],
        }
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                snapshot_at = datetime.now(UTC).isoformat(timespec="microseconds")
                schema_revision = _schema_revision(connection, backend)
                for table in _included_tables():
                    path = record_root / f"{table.name}.jsonl"
                    table_digest = hashlib.sha256()
                    count = 0
                    primary_key = list(table.primary_key.columns)
                    if not primary_key:
                        raise RecoveryError(
                            f"Portable table {table.name} has no stable primary key"
                        )
                    statement = select(table).order_by(*primary_key)
                    with path.open("xb") as output:
                        os.chmod(path, 0o600)
                        result = connection.execute(statement).mappings().yield_per(200)
                        for row in result:
                            row_values = dict(row)
                            encoded = _encode_row(table, row_values)
                            if len(encoded) > _MAX_RECORD_BYTES:
                                raise RecoveryError(
                                    f"A row in {table.name} exceeds its portable bound"
                                )
                            line = encoded + b"\n"
                            total_plaintext += len(line)
                            if total_plaintext > _MAX_PAYLOAD_BYTES:
                                raise RecoveryError(
                                    "Export exceeds its total size limit"
                                )
                            table_digest.update(line)
                            output.write(line)
                            count += 1
                            _snapshot_revisions(table.name, row_values, frozen)
                            if table.name == PrivateFile.__tablename__:
                                _object_reference(
                                    file_references,
                                    key=row["storage_key"],
                                    digest=row["content_hash"],
                                    size=row["byte_size"],
                                    role="private_file",
                                )
                            elif table.name == Calculation.__tablename__:
                                _object_reference(
                                    file_references,
                                    key=row["storage_key"],
                                    digest=row["content_hash"],
                                    size=None,
                                    role="report_artifact",
                                )
                            if count > _MAX_TABLE_ROWS:
                                raise RecoveryError(
                                    f"Table {table.name} exceeds its row-count limit"
                                )
                    total_rows += count
                    if total_rows > _MAX_TOTAL_ROWS:
                        raise RecoveryError("Export exceeds its total row-count limit")
                    tables[table.name] = {
                        "row_count": count,
                        "sha256": table_digest.hexdigest(),
                        "byte_count": path.stat().st_size,
                        "columns": [column.name for column in table.columns],
                    }

        for object_digest, reference in sorted(file_references.items()):
            content = file_store.read(
                f"{object_digest}.blob", max_bytes=_MAX_OBJECT_BYTES
            )
            if hashlib.sha256(content).hexdigest() != object_digest:
                raise RecoveryError("Private object hash did not match its storage key")
            if (
                reference["byte_size"] is not None
                and len(content) != reference["byte_size"]
            ):
                raise RecoveryError(
                    "Private object size did not match its database row"
                )
            if len(content) > _MAX_OBJECT_BYTES:
                raise RecoveryError("Private object exceeds the portable size limit")
            reference["byte_size"] = len(content)
            object_path = object_root / f"{object_digest}.blob"
            with object_path.open("xb") as output:
                os.chmod(object_path, 0o600)
                output.write(content)
            total_plaintext += len(content)
            if total_plaintext > _MAX_PAYLOAD_BYTES:
                raise RecoveryError("Export exceeds its total size limit")

        object_manifest = {
            digest: {
                "byte_size": reference["byte_size"],
                "roles": dict(sorted(reference["roles"].items())),
                "reference_count": sum(reference["roles"].values()),
            }
            for digest, reference in sorted(file_references.items())
        }
        frozen_manifest = {
            key: sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
            for key, items in frozen.items()
        }
        manifest = {
            "format": "personal-finance-portable-archive",
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source_snapshot_at": snapshot_at,
            "source_scope_id": source_scope_id,
            "source_backend": backend,
            "schema_revision": schema_revision,
            "schema_fingerprint": _schema_fingerprint(),
            "consistency": (
                "Finance rows were read in one read-only REPEATABLE READ transaction. "
                "Immutable content-addressed objects were read after that snapshot by "
                "their captured keys and verified against SHA-256 and size."
            ),
            "maintenance_policy": (
                "Pause publication and finance writes for the export window; this "
                "portable snapshot is complete only at the captured database "
                "snapshot and does not synchronize later writes."
            ),
            "conventions": {
                "decimal": "Base-10 strings preserve SQL NUMERIC values and scale.",
                "currency": (
                    "Three-letter currency codes are preserved verbatim per row."
                ),
                "timestamps": "ISO-8601 with UTC offset and microsecond precision.",
                "lineage": (
                    "All included table foreign keys and original source references "
                    "are retained."
                ),
            },
            "encryption": {
                "cipher": "AES-256-GCM chunked authenticated encryption",
                **_CHUNK_KDF,
                "chunk_bytes": _CHUNK_BYTES,
                "salt_and_nonce": "Random values stored in the encrypted file header.",
            },
            "tables": tables,
            "objects": object_manifest,
            "lineage": _lineage_manifest(),
            "frozen_revisions": frozen_manifest,
            "excluded_tables": _EXCLUDED_TABLES,
            "limits": {
                "maximum_archive_payload_bytes": _MAX_PAYLOAD_BYTES,
                "maximum_object_bytes": _MAX_OBJECT_BYTES,
                "maximum_rows": _MAX_TOTAL_ROWS,
            },
        }
        manifest_path = root / "manifest.json"
        manifest_bytes = json.dumps(
            manifest, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
        if len(manifest_bytes) > _MAX_MANIFEST_BYTES:
            raise RecoveryError("Archive manifest exceeds its size limit")
        if total_plaintext + len(manifest_bytes) > _MAX_PAYLOAD_BYTES:
            raise RecoveryError("Export exceeds its total size limit")
        with manifest_path.open("xb") as output:
            os.chmod(manifest_path, 0o600)
            output.write(manifest_bytes)
        payload_path = root / "payload.zip"
        with zipfile.ZipFile(
            payload_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
        ) as archive:
            archive.write(manifest_path, "manifest.json")
            for table_name in sorted(tables):
                archive.write(
                    record_root / f"{table_name}.jsonl",
                    f"records/{table_name}.jsonl",
                )
            for object_digest in sorted(object_manifest):
                archive.write(
                    object_root / f"{object_digest}.blob",
                    f"objects/{object_digest}.blob",
                )
        os.chmod(payload_path, 0o600)
        if payload_path.stat().st_size > _MAX_PAYLOAD_BYTES:
            raise RecoveryError("Compressed archive exceeds its payload size limit")
        _encrypt_payload(payload_path, destination_path, passphrase)

    return {
        "format_version": FORMAT_VERSION,
        "archive_sha256": _file_digest(destination_path),
        "table_count": len(tables),
        "row_count": total_rows,
        "object_count": len(file_references),
        "encrypted_bytes": destination_path.stat().st_size,
        "source_backend": backend,
    }


def _json_loads(data: bytes) -> Any:
    def reject_constant(_value: str) -> None:
        raise RecoveryError("Archive contains a non-finite JSON number")

    try:
        return json.loads(data, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("Archive JSON is malformed") from exc


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise RecoveryError("Archive manifest is malformed")
    if (
        manifest.get("format") != "personal-finance-portable-archive"
        or manifest.get("format_version") != FORMAT_VERSION
    ):
        raise RecoveryError("Archive format version is unsupported")
    if manifest.get("schema_fingerprint") != _schema_fingerprint():
        raise RecoveryError("Archive schema fingerprint is incompatible")
    if not isinstance(manifest.get("source_scope_id"), str) or not _SCOPE.fullmatch(
        manifest["source_scope_id"]
    ):
        raise RecoveryError("Archive source scope is malformed")
    backend = manifest.get("source_backend")
    revision = manifest.get("schema_revision")
    if backend == "postgres":
        if revision != _alembic_head():
            raise RecoveryError("Archive PostgreSQL schema revision is incompatible")
    else:
        raise RecoveryError("Archive source database backend is unsupported")
    for field in ("created_at", "source_snapshot_at"):
        try:
            timestamp = datetime.fromisoformat(manifest[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoveryError(f"Archive {field} timestamp is malformed") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise RecoveryError(f"Archive {field} timestamp must include an offset")
    if manifest.get("encryption") != {
        "cipher": "AES-256-GCM chunked authenticated encryption",
        **_CHUNK_KDF,
        "chunk_bytes": _CHUNK_BYTES,
        "salt_and_nonce": "Random values stored in the encrypted file header.",
    }:
        raise RecoveryError("Archive encryption metadata is incompatible")
    if not isinstance(manifest.get("consistency"), str) or not isinstance(
        manifest.get("maintenance_policy"), str
    ):
        raise RecoveryError("Archive consistency policy is missing")
    if manifest.get("excluded_tables") != _EXCLUDED_TABLES:
        raise RecoveryError("Archive excluded-table policy is incompatible")
    if manifest.get("lineage") != _lineage_manifest():
        raise RecoveryError("Archive foreign-key lineage is incompatible")
    tables = manifest.get("tables")
    expected_tables = {table.name: table for table in _included_tables()}
    if not isinstance(tables, dict) or set(tables) != set(expected_tables):
        raise RecoveryError("Archive table inventory is incomplete or unexpected")
    total_rows = 0
    for name, table in expected_tables.items():
        description = tables[name]
        if not isinstance(description, dict):
            raise RecoveryError(f"Archive table metadata is malformed: {name}")
        count = description.get("row_count")
        byte_count = description.get("byte_count")
        digest = description.get("sha256")
        columns = description.get("columns")
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 0 <= count <= _MAX_TABLE_ROWS
            or not isinstance(byte_count, int)
            or not 0 <= byte_count <= _MAX_PAYLOAD_BYTES
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or columns != [column.name for column in table.columns]
        ):
            raise RecoveryError(f"Archive table metadata is invalid: {name}")
        total_rows += count
    if total_rows > _MAX_TOTAL_ROWS:
        raise RecoveryError("Archive table inventory exceeds row-count limits")
    objects = manifest.get("objects")
    if not isinstance(objects, dict) or len(objects) > _MAX_TOTAL_ROWS:
        raise RecoveryError("Archive object inventory is malformed")
    for digest, item in objects.items():
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(item, dict)
            or not isinstance(item.get("byte_size"), int)
            or not 0 <= item["byte_size"] <= _MAX_OBJECT_BYTES
            or not isinstance(item.get("reference_count"), int)
            or item["reference_count"] < 1
            or not isinstance(item.get("roles"), dict)
            or not item["roles"]
        ):
            raise RecoveryError("Archive object metadata is invalid")
        if any(
            role not in {"private_file", "report_artifact"}
            or not isinstance(count, int)
            or count < 1
            for role, count in item["roles"].items()
        ):
            raise RecoveryError("Archive object role counts are invalid")
        if sum(item["roles"].values()) != item["reference_count"]:
            raise RecoveryError("Archive object reference count does not match roles")
    return manifest


def _validate_frozen_revisions(
    archive: zipfile.ZipFile, manifest: dict[str, Any]
) -> None:
    frozen: dict[str, list[dict[str, Any]]] = {
        "account_positions": [],
        "fund_snapshots": [],
        "transaction_imports": [],
        "transactions": [],
        "tax_lots": [],
    }
    tables = {table.name: table for table in _included_tables()}
    for name in tables:
        if name in {
            "accounts",
            "fund_snapshots",
            "transaction_imports",
            "financial_transactions",
            "tax_lots",
        }:
            for row in _table_rows(archive, tables[name], manifest["tables"][name]):
                _snapshot_revisions(name, row, frozen)
    normalized = {
        key: sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
        for key, items in frozen.items()
    }
    if manifest.get("frozen_revisions") != normalized:
        raise RecoveryError("Frozen publication revisions do not match archived rows")


def _table_rows(
    archive: zipfile.ZipFile, table: Table, description: dict[str, Any]
) -> Iterator[dict[str, Any]]:
    name = f"records/{table.name}.jsonl"
    digest = hashlib.sha256()
    count = 0
    with archive.open(name) as source:
        while line := source.readline(_MAX_RECORD_BYTES + 2):
            if not line.endswith(b"\n") or len(line) > _MAX_RECORD_BYTES + 1:
                raise RecoveryError(
                    f"Archive record framing is malformed: {table.name}"
                )
            digest.update(line)
            encoded = _json_loads(line[:-1])
            yield _decode_row(table, encoded)
            count += 1
            if count > description["row_count"]:
                raise RecoveryError(f"Archive row count exceeds metadata: {table.name}")
    if count != description["row_count"] or digest.hexdigest() != description["sha256"]:
        raise RecoveryError(f"Archive row hash or count mismatch: {table.name}")


def _actual_object_references(
    archive: zipfile.ZipFile, manifest: dict[str, Any]
) -> None:
    expected: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_name = {table.name: table for table in _included_tables()}
    for name in ("private_files", "portfolio_calculations"):
        if name not in by_name:
            continue
        for row in _table_rows(archive, by_name[name], manifest["tables"][name]):
            if name == "private_files":
                role = "private_file"
                size = row["byte_size"]
            else:
                role = "report_artifact"
                key = row["storage_key"]
                digest = row["content_hash"]
                if (
                    not isinstance(key, str)
                    or not _OBJECT_KEY.fullmatch(key)
                    or key != f"{digest}.blob"
                    or not isinstance(digest, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", digest)
                ):
                    raise RecoveryError("Report artifact identity is malformed")
                size = None
            key = row["storage_key"]
            digest = row["content_hash"]
            if key != f"{digest}.blob" or digest not in manifest["objects"]:
                raise RecoveryError("Archive row references an absent object")
            if size is not None and size != manifest["objects"][digest]["byte_size"]:
                raise RecoveryError("Archive object size differs from its file row")
            expected[digest][role] += 1
    actual = {
        digest: {role: count for role, count in item["roles"].items()}
        for digest, item in manifest["objects"].items()
    }
    if {key: dict(value) for key, value in expected.items()} != actual:
        raise RecoveryError("Archive object references do not match the manifest")


def _verify_zip(payload: Path) -> tuple[zipfile.ZipFile, dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(payload, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise RecoveryError("Encrypted payload is not a valid archive") from exc
    members = archive.infolist()
    names = [member.filename for member in members]
    if len(names) != len(set(names)) or any(
        name.startswith("/") or ".." in Path(name).parts for name in names
    ):
        archive.close()
        raise RecoveryError("Archive contains duplicate or unsafe paths")
    if (
        any(
            member.file_size > _MAX_PAYLOAD_BYTES
            or member.compress_size > _MAX_PAYLOAD_BYTES
            or member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            for member in members
        )
        or sum(member.file_size for member in members) > _MAX_PAYLOAD_BYTES
    ):
        archive.close()
        raise RecoveryError("Archive expands beyond its configured bound")
    if "manifest.json" not in names:
        archive.close()
        raise RecoveryError("Archive manifest is missing")
    try:
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > _MAX_MANIFEST_BYTES:
            raise RecoveryError("Archive manifest exceeds its size limit")
        manifest = _validate_manifest(_json_loads(archive.read("manifest.json")))
        expected_names = {"manifest.json"}
        expected_names.update(f"records/{name}.jsonl" for name in manifest["tables"])
        expected_names.update(
            f"objects/{digest}.blob" for digest in manifest["objects"]
        )
        if set(names) != expected_names:
            raise RecoveryError("Archive members do not match its manifest")
        for name, table in ((table.name, table) for table in _included_tables()):
            description = manifest["tables"][name]
            member = archive.getinfo(f"records/{name}.jsonl")
            if member.file_size != description["byte_count"]:
                raise RecoveryError(f"Archive table byte count mismatch: {name}")
            # Complete shape, codec, row count and digest validation before any
            # target object write or structured-data transaction.
            for _row in _table_rows(archive, table, description):
                pass
        _validate_frozen_revisions(archive, manifest)
        _actual_object_references(archive, manifest)
        for digest, description in manifest["objects"].items():
            info = archive.getinfo(f"objects/{digest}.blob")
            if info.file_size != description["byte_size"]:
                raise RecoveryError("Archive object byte count mismatch")
            hasher = hashlib.sha256()
            count = 0
            with archive.open(info) as source:
                while block := source.read(64 * 1024):
                    count += len(block)
                    hasher.update(block)
            if count != description["byte_size"] or hasher.hexdigest() != digest:
                raise RecoveryError("Archive object hash or size mismatch")
        return archive, manifest
    except BaseException:
        archive.close()
        raise


def verify_archive(archive_path: str | Path, passphrase: str) -> dict[str, Any]:
    """Authenticate and validate an archive without writing user data."""
    with _decrypted_payload(Path(archive_path), passphrase) as (archive_path, payload):
        archive, manifest = _verify_zip(payload)
        archive.close()
        return {
            "archive_sha256": _file_digest(archive_path),
            "format_version": FORMAT_VERSION,
            "source_backend": manifest["source_backend"],
            "schema_revision": manifest["schema_revision"],
            "table_count": len(manifest["tables"]),
            "row_count": sum(item["row_count"] for item in manifest["tables"].values()),
            "object_count": len(manifest["objects"]),
            "encrypted_bytes": archive_path.stat().st_size,
        }


def _read_restore_marker(marker: Path) -> dict[str, Any] | None:
    if not marker.exists() and not marker.is_symlink():
        return None
    if marker.is_symlink() or not marker.is_file():
        raise RecoveryError("Restore marker must be a regular private file")
    if marker.stat().st_size > 16_384:
        raise RecoveryError("Restore marker is unexpectedly large")
    try:
        content = json.loads(marker.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("Restore marker is malformed") from exc
    if not isinstance(content, dict):
        raise RecoveryError("Restore marker is malformed")
    return content


def _write_restore_marker(marker: Path, value: dict[str, Any]) -> None:
    temporary = marker.with_name(f".{marker.name}.{uuid.uuid4().hex}.tmp")
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, marker)
        os.chmod(marker, 0o600)
        directory_fd = os.open(marker.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _target_url(value: str) -> tuple[Any, str]:
    try:
        url = make_url(value)
    except Exception as exc:
        raise RecoveryError("A valid PF_RESTORE_DATABASE_URL is required") from exc
    if url.drivername != "postgresql+psycopg":
        raise RecoveryError("Recovery targets must use local PostgreSQL with psycopg")
    if url.query:
        raise RecoveryError("Recovery target URL query options are not supported")
    if (url.host or "").casefold() not in _LOOPBACK_HOSTS:
        raise RecoveryError("Recovery target must be a loopback PostgreSQL database")
    database = url.database
    if not database or not database.startswith("pf_restore_"):
        raise RecoveryError("Recovery database name must start with pf_restore_")
    return url, database


def _same_database(left: str, right: str) -> bool:
    try:
        first, second = make_url(left), make_url(right)
    except Exception:
        return False
    return (
        first.drivername == second.drivername
        and (first.host or "").casefold() == (second.host or "").casefold()
        and first.port == second.port
        and first.database == second.database
    )


def _target_empty(connection: Connection) -> bool:
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        raise RecoveryError("Recovery target is not migrated to the current schema")
    versions: list[str] = list(
        connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
    )
    if versions != [_alembic_head()]:
        raise RecoveryError("Recovery target schema is not at the current Alembic head")
    table_names = set(inspector.get_table_names())
    expected_names = set(Base.metadata.tables)
    if not expected_names.issubset(table_names):
        raise RecoveryError("Recovery target is missing current application tables")
    return all(
        connection.execute(select(table).limit(1)).first() is None
        for table in Base.metadata.sorted_tables
    )


def _target_matches_archive(
    engine: Engine,
    archive: zipfile.ZipFile,
    manifest: dict[str, Any],
    file_store: PrivateFileStore,
) -> bool:
    try:
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection:
            with connection.begin():
                if _target_empty(connection):
                    return False
                for table in Base.metadata.sorted_tables:
                    if table.name in _EXCLUDED_TABLES:
                        continue
                    digest = hashlib.sha256()
                    count = 0
                    for row in (
                        connection.execute(
                            select(table).order_by(*table.primary_key.columns)
                        )
                        .mappings()
                        .yield_per(200)
                    ):
                        digest.update(_encode_row(table, dict(row)) + b"\n")
                        count += 1
                    expected = manifest["tables"][table.name]
                    if (
                        count != expected["row_count"]
                        or digest.hexdigest() != expected["sha256"]
                    ):
                        return False
                for name in _EXCLUDED_TABLES:
                    table = Base.metadata.tables[name]
                    if connection.execute(select(table).limit(1)).first() is not None:
                        return False
        for digest, description in manifest["objects"].items():
            content = file_store.read(
                f"{digest}.blob", max_bytes=description["byte_size"]
            )
            if (
                len(content) != description["byte_size"]
                or hashlib.sha256(content).hexdigest() != digest
            ):
                return False
        return True
    except Exception:
        return False


def _schema_matches_archive(
    engine: Engine,
    schema: str,
    manifest: dict[str, Any],
) -> bool:
    """Verify bounded staging contents before they become the public schema."""
    try:
        with engine.connect() as raw_connection:
            connection = raw_connection.execution_options(
                schema_translate_map={None: schema}
            )
            for table in Base.metadata.sorted_tables:
                if table.name in _EXCLUDED_TABLES:
                    if connection.execute(select(table).limit(1)).first() is not None:
                        return False
                    continue
                count = int(
                    connection.execute(
                        select(func.count()).select_from(table)
                    ).scalar_one()
                )
                if count != manifest["tables"][table.name]["row_count"]:
                    return False
            for table_name, description in manifest["tables"].items():
                table = Base.metadata.tables[table_name]
                row_digest = hashlib.sha256()
                for row in (
                    connection.execute(
                        select(table).order_by(*table.primary_key.columns)
                    )
                    .mappings()
                    .yield_per(200)
                ):
                    row_digest.update(_encode_row(table, dict(row)) + b"\n")
                if row_digest.hexdigest() != description["sha256"]:
                    return False
        return True
    except Exception:
        return False


def restore_archive(
    archive_path: str | Path,
    passphrase: str,
    *,
    target_database_url: str,
    target_private_dir: str | Path,
    source_scope_id: str,
    target_scope_id: str,
    acknowledge_target: str,
    checkpoint: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Restore into a new loopback PG database; never creates or merges schema."""
    target_url, database_name = _target_url(target_database_url)
    if acknowledge_target != database_name:
        raise RecoveryError("Target database acknowledgement does not match")
    if not _SCOPE.fullmatch(target_scope_id):
        raise RecoveryError("A valid explicit target personal scope ID is required")
    if not _SCOPE.fullmatch(source_scope_id):
        raise RecoveryError("A valid explicit source scope ID is required")
    application_url = os.environ.get("DATABASE_URL")
    if application_url and _same_database(target_database_url, application_url):
        raise RecoveryError(
            "Recovery target matches the configured application database"
        )
    configured_database = os.environ.get("DATABASE_NAME", os.environ.get("POSTGRES_DB"))
    configured_host = os.environ.get(
        "DATABASE_HOST", os.environ.get("POSTGRES_HOST", "127.0.0.1")
    )
    if (
        configured_database == database_name
        and configured_host.casefold() == (target_url.host or "").casefold()
    ):
        raise RecoveryError(
            "Recovery target matches the configured application database"
        )
    directory = Path(target_private_dir).absolute()
    if directory.name != database_name:
        raise RecoveryError(
            "Private restore directory name must equal the target database"
        )
    if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
        raise RecoveryError("Private restore path must be a real directory")
    configured_files = os.environ.get("PRIVATE_FILE_DIR")
    if configured_files:
        current_private_dir = Path(configured_files).expanduser().absolute()
        if current_private_dir == directory:
            raise RecoveryError(
                "Recovery target matches the configured application file directory"
            )
    if not directory.exists():
        directory.mkdir(mode=0o700, parents=True)
    os.chmod(directory, 0o700)
    marker_path = directory / ".pf-restore.json"
    database_engine: Engine | None = None
    with _decrypted_payload(Path(archive_path), passphrase) as (archive_file, payload):
        archive, manifest = _verify_zip(payload)
        try:
            if manifest["source_scope_id"] != source_scope_id:
                raise RecoveryError("Confirmed source scope does not match the archive")
            marker_value = {
                "format_version": FORMAT_VERSION,
                "archive_sha256": _file_digest(archive_file),
                "database_name": database_name,
                "source_scope_id": source_scope_id,
                "target_scope_id": target_scope_id,
                "schema_fingerprint": _schema_fingerprint(),
                "staging_schema": f"pf_stage_{_file_digest(archive_file)[:16]}",
                "backup_schema": f"pf_previous_{_file_digest(archive_file)[:16]}",
                "phase": "prepared",
            }
            current_marker = _read_restore_marker(marker_path)
            if current_marker is None:
                if any(directory.iterdir()):
                    raise RecoveryError(
                        "Unmarked restore directory must be empty before recovery"
                    )
                _write_restore_marker(marker_path, marker_value)
            else:
                for key in (
                    "format_version",
                    "archive_sha256",
                    "database_name",
                    "source_scope_id",
                    "target_scope_id",
                    "schema_fingerprint",
                ):
                    if current_marker.get(key) != marker_value[key]:
                        raise RecoveryError(
                            "Restore directory belongs to another archive"
                        )
                if current_marker.get("phase") not in {
                    "prepared",
                    "objects_staged",
                    "publishing",
                    "published",
                }:
                    raise RecoveryError("Restore marker phase is unknown")

            database_engine = create_engine(target_url, poolclass=NullPool)
            with database_engine.connect() as connection:
                if connection.dialect.name != "postgresql":
                    raise RecoveryError("Recovery target must be PostgreSQL")
                if not _target_empty(connection):
                    if current_marker is not None and current_marker.get("phase") in {
                        "publishing",
                        "published",
                    }:
                        file_store = PrivateFileStore(directory)
                        if _target_matches_archive(
                            database_engine, archive, manifest, file_store
                        ):
                            marker_value["phase"] = "published"
                            _write_restore_marker(marker_path, marker_value)
                            return {
                                "restored": False,
                                "already_restored": True,
                                "archive_sha256": marker_value["archive_sha256"],
                                "table_count": len(manifest["tables"]),
                                "row_count": sum(
                                    item["row_count"]
                                    for item in manifest["tables"].values()
                                ),
                                "object_count": len(manifest["objects"]),
                            }
                    raise RecoveryError(
                        "Restore target contains rows; merge and overwrite are refused"
                    )
            file_store = PrivateFileStore(directory)
            for digest, description in manifest["objects"].items():
                content = archive.read(f"objects/{digest}.blob")
                if len(content) != description["byte_size"]:
                    raise RecoveryError("Object changed after archive validation")
                key, written_digest = file_store.put(content)
                if key != f"{digest}.blob" or written_digest != digest:
                    raise RecoveryError("Restored object identity did not match")
            marker_value["phase"] = "objects_staged"
            _write_restore_marker(marker_path, marker_value)
            staging_schema = f"pf_stage_{str(marker_value['archive_sha256'])[:16]}"
            backup_schema = f"pf_previous_{str(marker_value['archive_sha256'])[:16]}"
            marker_value["staging_schema"] = staging_schema
            marker_value["backup_schema"] = backup_schema
            marker_value["phase"] = "publishing"
            _write_restore_marker(marker_path, marker_value)
            with database_engine.connect() as connection:
                if not _target_empty(connection):
                    raise RecoveryError(
                        "Restore target became non-empty before publication"
                    )
                current_schemas = set(inspect(connection).get_schema_names())
            with database_engine.begin() as connection:
                if staging_schema not in current_schemas:
                    connection.execute(text(f'CREATE SCHEMA "{staging_schema}"'))
            with database_engine.begin() as connection:
                Base.metadata.create_all(
                    connection.execution_options(
                        schema_translate_map={None: staging_schema}
                    )
                )
                if not inspect(connection).has_table(
                    "alembic_version", schema=staging_schema
                ):
                    connection.execute(
                        text(
                            f'CREATE TABLE "{staging_schema}".alembic_version '
                            "(version_num VARCHAR(64) NOT NULL)"
                        )
                    )
                    connection.execute(
                        text(
                            f'INSERT INTO "{staging_schema}".alembic_version '
                            "(version_num) VALUES (:head)"
                        ),
                        {"head": _alembic_head()},
                    )

            for table in _included_tables():
                description = manifest["tables"][table.name]
                batch: list[dict[str, Any]] = []
                for row in _table_rows(archive, table, description):
                    if table.name == "accounts":
                        row["current_position_snapshot_id"] = None
                    batch.append(row)
                    if len(batch) == 200:
                        with database_engine.begin() as raw_connection:
                            connection = raw_connection.execution_options(
                                schema_translate_map={None: staging_schema}
                            )
                            connection.execute(
                                pg_insert(table).values(batch).on_conflict_do_nothing()
                            )
                        batch.clear()
                        if checkpoint is not None:
                            checkpoint("after_database_batch")
                if batch:
                    with database_engine.begin() as raw_connection:
                        connection = raw_connection.execution_options(
                            schema_translate_map={None: staging_schema}
                        )
                        connection.execute(
                            pg_insert(table).values(batch).on_conflict_do_nothing()
                        )
                    if checkpoint is not None:
                        checkpoint("after_database_batch")

            # Restore selected-snapshot pointers after every referenced row exists.
            accounts = Base.metadata.tables["accounts"]
            pointer_batch: list[dict[str, Any]] = []
            for row in _table_rows(archive, accounts, manifest["tables"]["accounts"]):
                if row["current_position_snapshot_id"] is not None:
                    pointer_batch.append(
                        {
                            "account_id": row["id"],
                            "snapshot_id": row["current_position_snapshot_id"],
                            "updated_at": row["updated_at"],
                        }
                    )
                if len(pointer_batch) == 200:
                    with database_engine.begin() as raw_connection:
                        connection = raw_connection.execution_options(
                            schema_translate_map={None: staging_schema}
                        )
                        connection.execute(
                            update(accounts)
                            .where(accounts.c.id == bindparam("account_id"))
                            .values(
                                current_position_snapshot_id=bindparam("snapshot_id"),
                                updated_at=bindparam("updated_at"),
                            ),
                            pointer_batch,
                        )
                    pointer_batch.clear()
            if pointer_batch:
                with database_engine.begin() as raw_connection:
                    connection = raw_connection.execution_options(
                        schema_translate_map={None: staging_schema}
                    )
                    connection.execute(
                        update(accounts)
                        .where(accounts.c.id == bindparam("account_id"))
                        .values(
                            current_position_snapshot_id=bindparam("snapshot_id"),
                            updated_at=bindparam("updated_at"),
                        ),
                        pointer_batch,
                    )
            if not _schema_matches_archive(database_engine, staging_schema, manifest):
                raise RecoveryError(
                    "Staged database content does not match the archive"
                )
            if checkpoint is not None:
                checkpoint("before_publish")
            with database_engine.begin() as connection:
                connection.execute(
                    text("SELECT version_num FROM alembic_version FOR UPDATE")
                ).all()
                if not _target_empty(connection):
                    raise RecoveryError(
                        "Restore target became non-empty before publication"
                    )
                schemas = set(inspect(connection).get_schema_names())
                if "public" not in schemas or staging_schema not in schemas:
                    raise RecoveryError("Staged schema is missing before publication")
                if backup_schema in schemas:
                    raise RecoveryError(
                        "A prior restore publication backup already exists"
                    )
                connection.execute(
                    text(f'ALTER SCHEMA public RENAME TO "{backup_schema}"')
                )
                connection.execute(
                    text(f'ALTER SCHEMA "{staging_schema}" RENAME TO public')
                )
            marker_value["phase"] = "published"
            _write_restore_marker(marker_path, marker_value)
            return {
                "restored": True,
                "already_restored": False,
                "archive_sha256": marker_value["archive_sha256"],
                "table_count": len(manifest["tables"]),
                "row_count": sum(
                    item["row_count"] for item in manifest["tables"].values()
                ),
                "object_count": len(manifest["objects"]),
            }
        finally:
            archive.close()
            if database_engine is not None:
                database_engine.dispose()
