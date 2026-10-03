"""Run the explicitly gated DSQL release suite and emit secret-free evidence.

This tool deliberately treats skipped tests as a blocked result. It records
hashes of the build inputs, schema plan, fixture suite and sanitized DSQL
configuration; raw endpoints, role names, credentials, pytest output, and
JUnit XML are never written to the evidence record.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = REPOSITORY_ROOT / "services" / "api"
EVIDENCE_VERSION = 1
FIXTURE_VERSION = "stage4-release-suite-v2"
REQUIRED_CASES = frozenset(
    {
        "test_real_dsql_populated_previous_schema_upgrade",
        "test_real_dsql_mid_migration_interruption_resume",
        "test_real_dsql_application_role_reconnects_after_iam_token_expiry",
        "test_real_dsql_migration_and_synthetic_persistence",
        "test_real_dsql_occ_conflict_uses_bounded_database_retry",
        "test_real_dsql_manual_replacement_history_and_scoped_identity",
        "test_real_dsql_auth_schema_and_session_round_trip",
        "test_real_dsql_application_role_reconnects_with_verified_tls",
        "test_real_dsql_stage1_golden_and_frozen_report",
        "test_real_dsql_stage1_502_rows_duplicate_and_history",
        "test_real_dsql_stage1_partial_staging_recovery",
        "test_real_dsql_stage1_concurrent_publication",
        "test_real_dsql_configured_safe_batch_limit_rejects_extra_row",
    }
)
UNVERIFIED_RELEASE_GATES: tuple[str, ...] = ()
CONFIG_KEYS = (
    "APP_ENV",
    "APP_PUBLIC_ORIGIN",
    "AUTH_ENABLED",
    "AUTH_ISSUER_URL",
    "AUTH_CLIENT_ID",
    "AUTH_COOKIE_SECURE",
    "AUTH_SESSION_TTL_SECONDS",
    "FILE_STORAGE_BACKEND",
    "PRIVATE_S3_BUCKET",
    "PRIVATE_S3_KMS_KEY_ID",
    "STATIC_ASSETS_BUCKET",
    "DATABASE_BACKEND",
    "AWS_REGION",
    "AURORA_DSQL_CLUSTER_ENDPOINT",
    "AURORA_DSQL_DB_USER",
    "AURORA_DSQL_MIGRATION_DB_USER",
    "DATABASE_POOL_SIZE",
    "DATABASE_MAX_OVERFLOW",
    "DATABASE_POOL_RECYCLE_SECONDS",
    "DATABASE_CONNECT_TIMEOUT_SECONDS",
    "MAX_IMPORT_ROWS",
    "MAX_IMPORT_FILE_BYTES",
    "MAX_PRIVATE_FILE_BYTES",
    "MAX_PDF_PAGES",
    "PDF_PARSER_TIMEOUT_SECONDS",
    "JOB_WORKER_ENABLED",
    "JOB_POLL_INTERVAL_SECONDS",
    "JOB_LEASE_SECONDS",
    "JOB_MAX_ATTEMPTS",
    "PERSONAL_AI_ENABLED",
    "DEMO_MODE",
)


class EvidenceError(ValueError):
    """Evidence is incomplete, stale, or cannot satisfy the release gate."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_paths(paths: list[Path], *, base: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(base).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _source_paths() -> tuple[list[Path], list[Path], list[Path]]:
    app_sources = sorted((API_ROOT / "app").rglob("*.py"))
    migrations = sorted((API_ROOT / "alembic" / "versions").glob("*.py"))
    build_files = [
        API_ROOT / "pyproject.toml",
        API_ROOT / "uv.lock",
        API_ROOT / "Dockerfile",
        REPOSITORY_ROOT / "package.json",
        REPOSITORY_ROOT / "pnpm-lock.yaml",
        REPOSITORY_ROOT / "pnpm-workspace.yaml",
        REPOSITORY_ROOT / "apps" / "web" / "package.json",
        REPOSITORY_ROOT / "apps" / "web" / "vite.config.ts",
    ]
    build_files.extend(app_sources)
    build_files.extend(migrations)
    build_files.extend(
        path
        for path in (REPOSITORY_ROOT / "apps" / "web" / "src").rglob("*")
        if path.is_file()
    )
    schema_files = [
        API_ROOT / "app" / "db" / "dsql_migrations.py",
        API_ROOT / "app" / "db" / "models.py",
        *migrations,
    ]
    fixture_files = sorted((API_ROOT / "tests").glob("test_*.py"))
    fixture_files.extend(
        path
        for test_dir in (
            REPOSITORY_ROOT / "apps" / "web" / "test",
            REPOSITORY_ROOT / "apps" / "web" / "e2e",
        )
        for path in sorted(test_dir.rglob("*"))
        if path.is_file()
    )
    fixture_files.append(
        REPOSITORY_ROOT / "scripts" / "stage4" / "test_infra_contract.py"
    )
    return build_files, schema_files, fixture_files


def _fingerprints() -> dict[str, str]:
    build_files, schema_files, fixture_files = _source_paths()
    return {
        "build_sha256": _hash_paths(build_files, base=REPOSITORY_ROOT),
        "schema_sha256": _hash_paths(schema_files, base=REPOSITORY_ROOT),
        "fixture_sha256": _hash_paths(fixture_files, base=REPOSITORY_ROOT),
    }


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise EvidenceError("Could not identify the immutable source revision")
    return commit


def _require_committed_api_source() -> None:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--",
            "services/api",
            "apps/web",
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
        ],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise EvidenceError("Commit all API, web, migration and test sources first")


def _configuration_fingerprint() -> str:
    safe_values = {key: os.environ.get(key) for key in CONFIG_KEYS}
    if (safe_values["AUTH_ENABLED"] or "").casefold() == "true":
        signing_key = os.environ.get("AUTH_SESSION_SIGNING_KEY", "")
        private_auth_inputs = {
            "client_secret": os.environ.get("AUTH_CLIENT_SECRET"),
            "subject": os.environ.get("AUTH_ALLOWED_SUBJECT"),
            "scope": os.environ.get("AUTH_PERSONAL_SCOPE_ID"),
        }
        if (
            len(signing_key) < 32
            or not private_auth_inputs["client_secret"]
            or not private_auth_inputs["subject"]
            or not private_auth_inputs["scope"]
        ):
            raise EvidenceError(
                "Enabled authentication requires a signing key, OIDC secret, "
                "and owner scope for configuration evidence"
            )
        private_auth_payload = json.dumps(
            private_auth_inputs, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        # Bind private identity and client credentials without storing a
        # dictionary-guessable hash of any one low-entropy value.
        safe_values["AUTH_PRIVATE_INPUTS_HMAC_SHA256"] = hmac.new(
            signing_key.encode("utf-8"), private_auth_payload, hashlib.sha256
        ).hexdigest()
    else:
        safe_values["AUTH_PRIVATE_INPUTS_HMAC_SHA256"] = None
    return _sha256(
        json.dumps(safe_values, sort_keys=True, separators=(",", ":")).encode()
    )


def _cluster_fingerprint() -> str:
    endpoint = os.environ.get("AURORA_DSQL_CLUSTER_ENDPOINT", "").strip().casefold()
    if not endpoint or ".dsql." not in endpoint or not endpoint.endswith(".on.aws"):
        raise EvidenceError("A configured Aurora DSQL endpoint is required")
    return _sha256(endpoint.encode("utf-8"))


def _preflight() -> None:
    required_values = {
        "RUN_DSQL_INTEGRATION": "1",
        "DSQL_TEST_CLUSTER": "disposable",
        "DATABASE_BACKEND": "aurora_dsql",
    }
    for key, expected in required_values.items():
        if os.environ.get(key) != expected:
            raise EvidenceError("Explicit disposable Aurora DSQL opt-in is required")
    for key in (
        "AWS_REGION",
        "AURORA_DSQL_DB_USER",
        "AURORA_DSQL_MIGRATION_DB_USER",
    ):
        if not os.environ.get(key):
            raise EvidenceError("Both scoped DSQL roles and AWS region are required")
    if os.environ["AURORA_DSQL_DB_USER"].casefold() == "admin":
        raise EvidenceError("The release suite must use the scoped application role")
    if os.environ["AURORA_DSQL_DB_USER"] == os.environ["AURORA_DSQL_MIGRATION_DB_USER"]:
        raise EvidenceError("Application and migration roles must be distinct")
    if os.environ.get("RUN_DSQL_TOKEN_EXPIRY_TEST") != "1":
        raise EvidenceError(
            "Explicit 16-minute IAM token expiry reconnect test opt-in is required"
        )
    if not re.fullmatch(
        r"sha256:[0-9a-f]{64}", os.environ.get("RELEASE_IMAGE_DIGEST", "")
    ):
        raise EvidenceError("A source-matched immutable OCI image digest is required")
    _require_committed_api_source()
    _cluster_fingerprint()
    _configuration_fingerprint()


def _parse_junit(path: Path) -> tuple[dict[str, int], set[str]]:
    root = ElementTree.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    counts = {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    names: set[str] = set()
    for suite in suites:
        counts["tests"] += int(suite.attrib.get("tests", "0"))
        counts["failed"] += int(suite.attrib.get("failures", "0"))
        counts["errors"] += int(suite.attrib.get("errors", "0"))
        counts["skipped"] += int(suite.attrib.get("skipped", "0"))
        for case in suite.findall("testcase"):
            case_name = case.attrib.get("name", "")
            if case_name:
                names.add(case_name)
    counts["passed"] = (
        counts["tests"] - counts["failed"] - counts["errors"] - counts["skipped"]
    )
    if counts["passed"] < 0 or any(value < 0 for value in counts.values()):
        raise EvidenceError("JUnit test result counts are inconsistent")
    return counts, names


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)


def _run_suite(evidence_path: Path) -> int:
    try:
        _preflight()
    except EvidenceError as exc:
        print(f"DSQL release suite blocked: {exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="finance-dsql-release-") as temp_dir:
        junit_path = Path(temp_dir) / "results.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--junitxml",
            str(junit_path),
            "tests/test_dsql_integration.py",
            "tests/test_stage1_dsql_integration.py",
        ]
        # Keep pytest's raw output and XML in a private temporary location. A
        # connector exception can contain an endpoint or request details.
        process = subprocess.run(
            command,
            cwd=API_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=1800,
        )
        if not junit_path.exists():
            print("DSQL release suite failed before producing test evidence")
            return 1
        try:
            counts, case_names = _parse_junit(junit_path)
        except (ElementTree.ParseError, OSError, EvidenceError):
            print("DSQL release suite produced invalid test evidence")
            return 1

    missing_cases = sorted(REQUIRED_CASES - case_names)
    result = "passed"
    if process.returncode != 0 or counts["failed"] or counts["errors"]:
        result = "failed"
    elif counts["skipped"] or missing_cases or counts["tests"] == 0:
        result = "blocked"
    elif UNVERIFIED_RELEASE_GATES:
        # A clean run of the available cases does not imply the entire required
        # migration/reconnect/batch matrix has been exercised.
        result = "blocked"
    now = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    fingerprints = _fingerprints()
    payload: dict[str, Any] = {
        "evidence_version": EVIDENCE_VERSION,
        "suite": "aurora-dsql-stage4-release",
        "result": result,
        "executed_at_utc": now,
        "git_commit": _git_commit(),
        "backend": "aurora_dsql",
        "image_digest": os.environ["RELEASE_IMAGE_DIGEST"],
        "cluster_identity_sha256": _cluster_fingerprint(),
        "configuration_sha256": _configuration_fingerprint(),
        "fixture_version": FIXTURE_VERSION,
        **fingerprints,
        "tests": counts,
        "executed_cases": sorted(case_names),
        "missing_required_cases": missing_cases,
        "unverified_release_gates": list(UNVERIFIED_RELEASE_GATES),
        "credentials_recorded": False,
        "raw_junit_recorded": False,
    }
    _atomic_json(evidence_path, payload)
    print(
        f"DSQL suite {result}: {counts['passed']} passed, "
        f"{counts['failed'] + counts['errors']} failed, "
        f"{counts['skipped']} skipped; evidence written without endpoint or secrets"
    )
    return 0 if result == "passed" else 1


def validate_evidence(
    path: Path, *, require_current_runtime: bool = False
) -> dict[str, Any]:
    try:
        evidence = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("Evidence file cannot be read") from exc
    if (
        not isinstance(evidence, dict)
        or evidence.get("evidence_version") != EVIDENCE_VERSION
    ):
        raise EvidenceError("Unsupported DSQL evidence format")
    if evidence.get("result") != "passed":
        raise EvidenceError("DSQL evidence did not pass")
    if evidence.get("backend") != "aurora_dsql":
        raise EvidenceError("Evidence was not produced by Aurora DSQL")
    if evidence.get("suite") != "aurora-dsql-stage4-release":
        raise EvidenceError("Evidence was not produced by the required Stage 4 suite")
    if not isinstance(evidence.get("image_digest"), str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", evidence["image_digest"]
    ):
        raise EvidenceError("Evidence is missing an immutable OCI image digest")
    if evidence.get("fixture_version") != FIXTURE_VERSION:
        raise EvidenceError("DSQL synthetic fixture version changed")
    tests = evidence.get("tests")
    count_keys = ("tests", "passed", "failed", "errors", "skipped")
    if not isinstance(tests, dict) or any(
        not isinstance(tests.get(key), int) or isinstance(tests.get(key), bool)
        for key in count_keys
    ):
        raise EvidenceError("DSQL test counts are malformed")
    if any(tests[key] < 0 for key in count_keys) or any(
        tests[key] != value
        for key, value in {"failed": 0, "errors": 0, "skipped": 0}.items()
    ):
        raise EvidenceError("Failed, errored or skipped checks cannot pass the gate")
    if tests["tests"] <= 0 or tests["passed"] != tests["tests"]:
        raise EvidenceError("DSQL suite is incomplete")
    if evidence.get("missing_required_cases") != []:
        raise EvidenceError("Required release tests are missing")
    executed_cases = evidence.get("executed_cases")
    if (
        not isinstance(executed_cases, list)
        or not all(isinstance(case, str) for case in executed_cases)
        or len(executed_cases) != len(set(executed_cases))
        or not REQUIRED_CASES.issubset(set(executed_cases))
    ):
        raise EvidenceError("Evidence does not list every required release test")
    if evidence.get("unverified_release_gates") != []:
        raise EvidenceError("Required live DSQL matrix evidence is still outstanding")
    fingerprints = _fingerprints()
    for key, current in fingerprints.items():
        if evidence.get(key) != current:
            raise EvidenceError(f"Stale DSQL evidence: {key} changed")
    if evidence.get("git_commit") != _git_commit():
        raise EvidenceError("DSQL evidence belongs to a different source revision")
    for key in ("cluster_identity_sha256", "configuration_sha256"):
        value = evidence.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise EvidenceError("DSQL evidence metadata is incomplete")
    if require_current_runtime:
        _preflight()
        if evidence["image_digest"] != os.environ["RELEASE_IMAGE_DIGEST"]:
            raise EvidenceError("DSQL evidence names a different immutable image")
        if evidence["configuration_sha256"] != _configuration_fingerprint():
            raise EvidenceError("DSQL evidence configuration does not match this run")
        if evidence["cluster_identity_sha256"] != _cluster_fingerprint():
            raise EvidenceError("DSQL evidence belongs to a different cluster")
    if (
        evidence.get("credentials_recorded") is not False
        or evidence.get("raw_junit_recorded") is not False
    ):
        raise EvidenceError("DSQL evidence must not contain credentials or raw tests")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="run the gated real-cluster suite")
    run_parser.add_argument("--evidence", type=Path, required=True)
    check_parser = subparsers.add_parser(
        "check", help="validate passed evidence against the current build inputs"
    )
    check_parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        return _run_suite(args.evidence)
    try:
        evidence = validate_evidence(args.evidence, require_current_runtime=True)
    except EvidenceError as exc:
        print(f"DSQL release gate blocked: {exc}", file=sys.stderr)
        return 1
    print(
        "DSQL release gate passed for immutable build "
        f"{evidence['git_commit'][:12]} with {evidence['tests']['passed']} tests"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
