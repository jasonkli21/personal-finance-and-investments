"""Verify a hash-bound Stage 4 release evidence bundle without deploying it.

The gate only reads local evidence artifacts. It never contacts GCP or changes
infrastructure. Missing, skipped, failed, stale, or mismatched evidence blocks
promotion. Operator approvals remain attestations whose referenced artifacts
must be reviewed through the organization's chosen approval process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from app.release import neon_evidence

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_VERSION = 1
MAX_JSON_BYTES = 1_048_576
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_AGE = timedelta(days=30)
REQUIRED_GATES = {
    "target_configuration": ("approval", "production"),
    "immutable_infrastructure_plan": ("approval", "production"),
    "authenticated_https_private_gcs": ("tests", "synthetic_launch"),
    "real_neon_release_suite": ("neon", "neon_test"),
    "cost_and_budget_approval": ("approval", "production"),
    "encrypted_cloud_recovery": ("tests", "synthetic_launch"),
    "operations_rehearsal": ("tests", "synthetic_launch"),
    "production_release_approval": ("approval", "production"),
}
RELEASE_KEYS = (
    "git_commit",
    "build_sha256",
    "schema_sha256",
    "fixture_sha256",
    "infrastructure_sha256",
    "configuration_sha256",
    "image_digest",
)
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")


class GateError(ValueError):
    """A release artifact is missing, stale, malformed, or unsafe."""


def _sha256_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(128 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _release_sources() -> tuple[list[Path], list[Path]]:
    infra = REPOSITORY_ROOT / "infra"
    infra_paths = sorted(
        path
        for path in infra.rglob("*")
        if path.is_file()
        and ".terraform" not in path.parts
        and path.suffix in {".tf", ".hcl"}
    )
    infra_paths.extend(
        path
        for path in sorted((REPOSITORY_ROOT / "scripts" / "stage4").rglob("*"))
        if path.is_file() and path.suffix in {".py", ".sh"}
    )
    config_paths = [
        REPOSITORY_ROOT / "services" / "api" / "app" / "config.py",
        REPOSITORY_ROOT / ".env.example",
    ]
    return sorted(infra_paths), sorted(config_paths)


def _require_committed_release_sources() -> None:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "services/api",
            "apps/web",
            "infra",
            "scripts/stage4",
            "tests/infra",
            "fixtures",
            ".env.example",
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
        raise GateError(
            "Release source and tests must be committed before evidence check"
        )


def _current_release(image_digest: str | None = None) -> dict[str, str]:
    _require_committed_release_sources()
    image = image_digest or os.environ.get("RELEASE_IMAGE_DIGEST", "")
    if not IMAGE_RE.fullmatch(image):
        raise GateError("A source-matched immutable OCI image digest is required")
    infrastructure, config = _release_sources()
    release = {
        "git_commit": neon_evidence._git_commit(),
        **neon_evidence._fingerprints(),
        "infrastructure_sha256": _sha256_paths(infrastructure),
        "configuration_sha256": _sha256_paths(config),
        "image_digest": image,
    }
    _validate_release_record(release)
    return release


def _validate_release_record(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(RELEASE_KEYS):
        raise GateError("Release fingerprint record is incomplete")
    release: dict[str, str] = {}
    for key in RELEASE_KEYS:
        field = value.get(key)
        if not isinstance(field, str):
            raise GateError("Release fingerprints are invalid")
        release[key] = field
    if not COMMIT_RE.fullmatch(release["git_commit"]) or not IMAGE_RE.fullmatch(
        release["image_digest"]
    ):
        raise GateError("Release identity is invalid")
    for key in set(RELEASE_KEYS) - {"git_commit", "image_digest"}:
        if not SHA256_RE.fullmatch(release[key]):
            raise GateError("Release fingerprints are invalid")
    return release


def _write_json(path: Path, payload: dict[str, Any], *, exclusive: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        if exclusive:
            raise GateError("Output already exists")
        if path.is_symlink() or not path.is_file():
            raise GateError("Output path is unsafe")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            os.link(temporary, path)
            temporary.unlink()
        else:
            os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def create_template(path: Path) -> None:
    release = _current_release()
    payload = {
        "evidence_version": EVIDENCE_VERSION,
        "release": release,
        "gates": {gate: None for gate in REQUIRED_GATES},
        "note": "Empty gate entries are blocked; this template is not launch evidence.",
    }
    _write_json(path, payload, exclusive=True)


def _read_json(path: Path, *, limit: int = MAX_JSON_BYTES) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise GateError("Evidence file is unsafe or exceeds its size limit")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GateError("Evidence file is unreadable") from exc
    if not isinstance(value, dict):
        raise GateError("Evidence file must contain a JSON object")
    return value


def _bundle_path(bundle_root: Path, relative_value: Any) -> Path:
    if (
        not isinstance(relative_value, str)
        or not relative_value
        or "\\" in relative_value
    ):
        raise GateError("Evidence artifact path is invalid")
    relative = PurePosixPath(relative_value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise GateError("Evidence artifact path must stay inside the bundle")
    candidate = bundle_root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(bundle_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise GateError("Evidence artifact is missing or outside the bundle") from exc
    if candidate.is_symlink() or not resolved.is_file():
        raise GateError("Evidence artifact must be a regular file")
    if resolved.stat().st_size > MAX_ARTIFACT_BYTES:
        raise GateError("Evidence artifact exceeds its size limit")
    return resolved


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise GateError("Evidence timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError("Evidence timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise GateError("Evidence timestamp must include a timezone")
    now = datetime.now(UTC)
    parsed = parsed.astimezone(UTC)
    if parsed > now + timedelta(minutes=5) or now - parsed > MAX_EVIDENCE_AGE:
        raise GateError("Evidence is future-dated or older than 30 days")
    return parsed


def _validate_tests(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise GateError("Test evidence is missing counts")
    keys = ("tests", "passed", "failed", "errors", "skipped")
    if any(
        not isinstance(value.get(key), int) or isinstance(value.get(key), bool)
        for key in keys
    ):
        raise GateError("Test evidence counts are invalid")
    counts = {key: value[key] for key in keys}
    if (
        counts["tests"] <= 0
        or counts["passed"] != counts["tests"]
        or counts["failed"] != 0
        or counts["errors"] != 0
        or counts["skipped"] != 0
    ):
        raise GateError("Failed, skipped, or empty checks cannot pass the release gate")
    return counts


def _validate_manual_evidence(
    path: Path,
    *,
    bundle_root: Path,
    gate_id: str,
    expected_kind: str,
    expected_context: str,
    expected_context_configurations: dict[str, str],
    release: dict[str, str],
    context_configurations: dict[str, str],
) -> dict[str, Any]:
    evidence = _read_json(path)
    if evidence.get("evidence_version") != EVIDENCE_VERSION:
        raise GateError("Unsupported gate evidence format")
    if (
        evidence.get("gate_id") != gate_id
        or evidence.get("result") != "passed"
        or evidence.get("evidence_kind") != expected_kind
        or evidence.get("configuration_context") != expected_context
    ):
        raise GateError("Evidence does not satisfy its required gate")
    if _validate_release_record(evidence.get("release")) != release:
        raise GateError("Evidence is bound to a different release")
    config_hash = evidence.get("environment_configuration_sha256")
    if not isinstance(config_hash, str) or not SHA256_RE.fullmatch(config_hash):
        raise GateError("Evidence configuration fingerprint is missing")
    previous = context_configurations.get(expected_context)
    if previous is not None and previous != config_hash:
        raise GateError("Evidence configuration fingerprints do not match")
    context_configurations[expected_context] = config_hash
    if expected_context_configurations.get(expected_context) != config_hash:
        raise GateError(
            "Evidence configuration does not match the independently supplied "
            f"current {expected_context} configuration"
        )
    _parse_timestamp(evidence.get("verified_at_utc"))
    if evidence.get("unverified_gates") != []:
        raise GateError("Evidence has outstanding required checks")
    if (
        evidence.get("credentials_recorded") is not False
        or evidence.get("raw_logs_recorded") is not False
    ):
        raise GateError("Evidence must not contain credentials or raw logs")

    artifact = _bundle_path(bundle_root, evidence.get("artifact_path"))
    actual_hash = _file_sha256(artifact)
    if evidence.get("artifact_sha256") != actual_hash:
        raise GateError("Evidence artifact hash does not match")

    result: dict[str, Any] = {
        "result": "passed",
        "evidence_record_sha256": _file_sha256(path),
        "artifact_sha256": actual_hash,
        "environment_configuration_sha256": config_hash,
        "verified_at_utc": evidence["verified_at_utc"],
    }
    if expected_kind == "tests":
        result["tests"] = _validate_tests(evidence.get("tests"))
    else:
        approval = evidence.get("approval")
        if not isinstance(approval, dict):
            raise GateError("Operator approval reference is missing")
        for key in ("reference", "approver_reference"):
            value = approval.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise GateError("Operator approval reference is invalid")
    return result


def _validate_neon_evidence(
    path: Path,
    *,
    expected_release: dict[str, str],
    context_configurations: dict[str, str],
    expected_context_configurations: dict[str, str],
) -> dict[str, Any]:
    evidence = neon_evidence.validate_evidence(path, require_current_runtime=True)
    _parse_timestamp(evidence.get("executed_at_utc"))
    if not isinstance(
        evidence.get("database_identity_sha256"), str
    ) or not SHA256_RE.fullmatch(evidence["database_identity_sha256"]):
        raise GateError("Neon evidence is missing its cluster identity hash")
    for key in (
        "git_commit",
        "build_sha256",
        "schema_sha256",
        "fixture_sha256",
        "image_digest",
    ):
        if evidence.get(key) != expected_release[key]:
            raise GateError("Neon evidence is bound to a different release")
    config_hash = evidence.get("configuration_sha256")
    if not isinstance(config_hash, str) or not SHA256_RE.fullmatch(config_hash):
        raise GateError("Neon environment configuration fingerprint is missing")
    if expected_context_configurations.get("neon_test") != config_hash:
        raise GateError(
            "Neon configuration does not match the independent current test "
            "target configuration"
        )
    previous = context_configurations.get("neon_test")
    if previous is not None and previous != config_hash:
        raise GateError("Neon test configuration fingerprints do not match")
    context_configurations["neon_test"] = config_hash
    return {
        "result": "passed",
        "artifact_sha256": _file_sha256(path),
        "evidence_record_sha256": _file_sha256(path),
        "environment_configuration_sha256": config_hash,
        "database_identity_sha256": evidence["database_identity_sha256"],
        "verified_at_utc": evidence["executed_at_utc"],
        "tests": evidence["tests"],
    }


def evaluate_manifest(
    manifest_path: Path,
    *,
    current_release: dict[str, str] | None = None,
    expected_context_configurations: dict[str, str] | None = None,
    validate_neon_runtime: bool = True,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    if manifest.get("evidence_version") != EVIDENCE_VERSION:
        raise GateError("Unsupported Stage 4 evidence bundle")
    release = _validate_release_record(manifest.get("release"))
    expected = current_release or _current_release()
    expected = _validate_release_record(expected)
    if release != expected:
        raise GateError("Evidence bundle does not match the current immutable release")
    expected_configs = expected_context_configurations
    if expected_configs is None:
        raise GateError("Independent current target configuration hashes are required")
    required_contexts = {context for _, context in REQUIRED_GATES.values()}
    if (
        not isinstance(expected_configs, dict)
        or set(expected_configs) != required_contexts
        or any(
            not isinstance(value, str) or not SHA256_RE.fullmatch(value)
            for value in expected_configs.values()
        )
    ):
        raise GateError(
            "Expected target configuration record is incomplete or malformed"
        )
    gates = manifest.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(REQUIRED_GATES):
        raise GateError("Required Stage 4 gate entries are missing or unknown")

    bundle_root = manifest_path.parent.resolve(strict=True)
    contexts: dict[str, str] = {}
    checked: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    for gate_id, (kind, context) in REQUIRED_GATES.items():
        relative_path = gates.get(gate_id)
        try:
            evidence_path = _bundle_path(bundle_root, relative_path)
            if kind == "neon":
                outcome = (
                    _validate_neon_evidence(
                        evidence_path,
                        expected_release=release,
                        context_configurations=contexts,
                        expected_context_configurations=expected_configs,
                    )
                    if validate_neon_runtime
                    else _validate_neon_structure(
                        evidence_path,
                        expected_release=release,
                        context_configurations=contexts,
                        expected_context_configurations=expected_configs,
                    )
                )
            else:
                outcome = _validate_manual_evidence(
                    evidence_path,
                    bundle_root=bundle_root,
                    gate_id=gate_id,
                    expected_kind=kind,
                    expected_context=context,
                    expected_context_configurations=expected_configs,
                    release=release,
                    context_configurations=contexts,
                )
            checked[gate_id] = outcome
        except (
            GateError,
            neon_evidence.EvidenceError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ):
            checked[gate_id] = {"result": "blocked"}
            blocked.append(gate_id)
    return {
        "evidence_version": EVIDENCE_VERSION,
        "result": "blocked" if blocked else "passed",
        "checked_at_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "release": release,
        "manifest_sha256": _file_sha256(manifest_path),
        "gates": checked,
        "blocked_gates": blocked,
        "credentials_recorded": False,
        "raw_logs_recorded": False,
        "deployment_performed": False,
    }


def _validate_neon_structure(
    path: Path,
    *,
    expected_release: dict[str, str],
    context_configurations: dict[str, str],
    expected_context_configurations: dict[str, str],
) -> dict[str, Any]:
    """Validate the Neon record structure in offline unit tests only."""
    evidence = _read_json(path)
    if (
        evidence.get("evidence_version") != neon_evidence.EVIDENCE_VERSION
        or evidence.get("suite") != "neon-postgres-stage4-release"
        or evidence.get("result") != "passed"
        or evidence.get("backend") != "postgres"
        or evidence.get("fixture_version") != neon_evidence.FIXTURE_VERSION
        or evidence.get("unverified_release_gates") != []
        or evidence.get("missing_required_cases") != []
    ):
        raise GateError("Neon suite is not complete")
    for key in (
        "git_commit",
        "build_sha256",
        "schema_sha256",
        "fixture_sha256",
        "image_digest",
    ):
        if evidence.get(key) != expected_release[key]:
            raise GateError("Neon evidence is bound to a different release")
    counts = evidence.get("tests")
    _validate_tests(counts)
    cases = evidence.get("executed_cases")
    if (
        not isinstance(cases, list)
        or not all(isinstance(case, str) for case in cases)
        or len(cases) != len(set(cases))
        or not neon_evidence.REQUIRED_CASES.issubset(set(cases))
    ):
        raise GateError("Neon suite did not execute every required test")
    _parse_timestamp(evidence.get("executed_at_utc"))
    cluster_hash = evidence.get("database_identity_sha256")
    if not isinstance(cluster_hash, str) or not SHA256_RE.fullmatch(cluster_hash):
        raise GateError("Neon evidence is missing its cluster identity hash")
    if (
        evidence.get("credentials_recorded") is not False
        or evidence.get("raw_junit_recorded") is not False
    ):
        raise GateError("Neon evidence must not record credentials or raw tests")
    config_hash = evidence.get("configuration_sha256")
    if not isinstance(config_hash, str) or not SHA256_RE.fullmatch(config_hash):
        raise GateError("Neon test configuration fingerprint is missing")
    if expected_context_configurations.get("neon_test") != config_hash:
        raise GateError(
            "Neon configuration does not match the independent current test "
            "target configuration"
        )
    previous = context_configurations.get("neon_test")
    if previous is not None and previous != config_hash:
        raise GateError("Neon test configuration fingerprints do not match")
    context_configurations["neon_test"] = config_hash
    return {
        "result": "passed",
        "artifact_sha256": _file_sha256(path),
        "evidence_record_sha256": _file_sha256(path),
        "environment_configuration_sha256": config_hash,
        "database_identity_sha256": cluster_hash,
        "verified_at_utc": evidence.get("executed_at_utc"),
        "tests": counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    template = subparsers.add_parser(
        "template", help="write a blocked evidence bundle for this image digest"
    )
    template.add_argument("--output", type=Path, required=True)
    check = subparsers.add_parser(
        "check", help="verify the complete evidence bundle without deployment"
    )
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--report", type=Path, required=True)
    check.add_argument(
        "--expected-configurations",
        type=Path,
        required=True,
        help=(
            "independently reviewed JSON mapping each target context to its "
            "current canonical SHA-256"
        ),
    )
    args = parser.parse_args()
    try:
        if args.command == "template":
            create_template(args.output)
            print("Blocked Stage 4 evidence template written; no gate was verified")
            return 0
        expected_configs = _read_json(args.expected_configurations)
        report = evaluate_manifest(
            args.manifest,
            expected_context_configurations=expected_configs,
        )
        _write_json(args.report, report, exclusive=False)
    except (
        GateError,
        neon_evidence.EvidenceError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        KeyError,
    ):
        print("Stage 4 release gate blocked; the evidence bundle was not accepted")
        return 2
    if report["result"] != "passed":
        print(
            "Stage 4 release gate blocked: "
            f"{len(report['blocked_gates'])} required gates are incomplete"
        )
        return 1
    print("Stage 4 evidence checks passed for the current immutable release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
