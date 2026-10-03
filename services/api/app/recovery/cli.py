"""Operator-only command line for encrypted export, verification and restore."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.config import load_settings
from app.db.engine import DatabaseEngineFactory
from app.recovery.archive import (
    RecoveryError,
    export_database,
    restore_archive,
    verify_archive,
)
from app.storage.factory import create_file_store


def _passphrase(*, confirm: bool) -> str:
    first = getpass.getpass("Archive passphrase: ")
    if confirm:
        second = getpass.getpass("Repeat archive passphrase: ")
        if first != second:
            raise RecoveryError("Passphrases did not match")
    return first


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.recovery.cli",
        description="Create and restore encrypted portable finance archives.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Create a read-only source snapshot.")
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--scope-id", required=True)
    verify = commands.add_parser("verify", help="Authenticate and validate an archive.")
    verify.add_argument("--archive", required=True, type=Path)
    restore = commands.add_parser(
        "restore", help="Restore into a new isolated loopback PostgreSQL database."
    )
    restore.add_argument("--archive", required=True, type=Path)
    restore.add_argument("--target-private-dir", required=True, type=Path)
    restore.add_argument("--source-scope-id", required=True)
    restore.add_argument("--target-scope-id", required=True)
    restore.add_argument(
        "--acknowledge-target",
        required=True,
        help="Must exactly equal the pf_restore_ database name.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "export":
            settings = load_settings()
            if (
                settings.auth_enabled
                and args.scope_id != settings.auth_personal_scope_id
            ):
                raise RecoveryError(
                    "Export scope must match the server-configured personal scope"
                )
            engine = DatabaseEngineFactory.create(settings, purpose="application")
            try:
                result = export_database(
                    engine,
                    create_file_store(settings),
                    args.output,
                    backend=settings.database_backend,
                    source_scope_id=args.scope_id,
                    passphrase=_passphrase(confirm=True),
                )
            finally:
                engine.dispose()
        elif args.command == "verify":
            result = verify_archive(args.archive, _passphrase(confirm=False))
        else:
            target_url = os.environ.get("PF_RESTORE_DATABASE_URL")
            if not target_url:
                raise RecoveryError(
                    "Set PF_RESTORE_DATABASE_URL to an explicitly prepared "
                    "loopback target"
                )
            result = restore_archive(
                args.archive,
                _passphrase(confirm=False),
                target_database_url=target_url,
                target_private_dir=args.target_private_dir,
                source_scope_id=args.source_scope_id,
                target_scope_id=args.target_scope_id,
                acknowledge_target=args.acknowledge_target,
            )
    except RecoveryError as exc:
        print(f"recovery blocked: {exc}", file=sys.stderr)
        return 2
    except (SQLAlchemyError, OSError, RuntimeError):
        # Driver errors can include endpoints and database context. Do not emit
        # their text or traceback into an operator transcript.
        print(
            "recovery failed; database and file details were suppressed",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
