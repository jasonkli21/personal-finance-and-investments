from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.release import dsql_evidence
from app.release.stage4_gate import (
    REQUIRED_GATES,
    GateError,
    evaluate_manifest,
)

RELEASE = {
    "git_commit": "a" * 40,
    "build_sha256": "1" * 64,
    "schema_sha256": "2" * 64,
    "fixture_sha256": "3" * 64,
    "infrastructure_sha256": "4" * 64,
    "configuration_sha256": "5" * 64,
    "image_digest": "sha256:" + "6" * 64,
}
CONTEXTS = {
    "production": "7" * 64,
    "synthetic_launch": "8" * 64,
    "dsql_test": "9" * 64,
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))


def _dsql_evidence() -> dict[str, Any]:
    return {
        "evidence_version": dsql_evidence.EVIDENCE_VERSION,
        "suite": "aurora-dsql-stage4-release",
        "result": "passed",
        "executed_at_utc": _now(),
        "git_commit": RELEASE["git_commit"],
        "backend": "aurora_dsql",
        "image_digest": RELEASE["image_digest"],
        "cluster_identity_sha256": "c" * 64,
        "configuration_sha256": CONTEXTS["dsql_test"],
        "fixture_version": dsql_evidence.FIXTURE_VERSION,
        "build_sha256": RELEASE["build_sha256"],
        "schema_sha256": RELEASE["schema_sha256"],
        "fixture_sha256": RELEASE["fixture_sha256"],
        "tests": {
            "tests": len(dsql_evidence.REQUIRED_CASES),
            "passed": len(dsql_evidence.REQUIRED_CASES),
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
        "executed_cases": sorted(dsql_evidence.REQUIRED_CASES),
        "missing_required_cases": [],
        "unverified_release_gates": [],
        "credentials_recorded": False,
        "raw_junit_recorded": False,
    }


def _bundle(tmp_path: Path) -> Path:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    common_artifact = artifact_dir / "proof.txt"
    common_artifact.write_text("synthetic evidence artifact\n")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    gate_paths: dict[str, str] = {}
    dsql_path = evidence_dir / "dsql.json"
    _write_json(dsql_path, _dsql_evidence())
    gate_paths["real_dsql_release_suite"] = "evidence/dsql.json"

    for gate_id, (kind, context) in REQUIRED_GATES.items():
        if kind == "dsql":
            continue
        artifact_path = "artifacts/proof.txt"
        evidence: dict[str, Any] = {
            "evidence_version": 1,
            "gate_id": gate_id,
            "result": "passed",
            "evidence_kind": kind,
            "configuration_context": context,
            "environment_configuration_sha256": CONTEXTS[context],
            "release": RELEASE,
            "verified_at_utc": _now(),
            "artifact_path": artifact_path,
            "artifact_sha256": hashlib.sha256(common_artifact.read_bytes()).hexdigest(),
            "unverified_gates": [],
            "credentials_recorded": False,
            "raw_logs_recorded": False,
        }
        if kind == "tests":
            evidence["tests"] = {
                "tests": 5,
                "passed": 5,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
            }
        else:
            evidence["approval"] = {
                "reference": f"approval-{gate_id}",
                "approver_reference": "reviewer-1",
            }
        path = evidence_dir / f"{gate_id}.json"
        _write_json(path, evidence)
        gate_paths[gate_id] = f"evidence/{path.name}"
    manifest = tmp_path / "manifest.json"
    _write_json(
        manifest,
        {"evidence_version": 1, "release": RELEASE, "gates": gate_paths},
    )
    return manifest


def _expected_configs() -> dict[str, str]:
    return dict(CONTEXTS)


def test_release_gate_accepts_complete_fresh_hash_bound_bundle(tmp_path: Path) -> None:
    manifest = _bundle(tmp_path)

    report = evaluate_manifest(
        manifest,
        current_release=RELEASE,
        expected_context_configurations=_expected_configs(),
        validate_dsql_runtime=False,
    )

    assert report["result"] == "passed"
    assert report["blocked_gates"] == []
    assert report["deployment_performed"] is False
    assert set(report["gates"]) == set(REQUIRED_GATES)
    assert (
        report["gates"]["real_dsql_release_suite"]["cluster_identity_sha256"]
        == "c" * 64
    )


@pytest.mark.parametrize(
    ("mutation", "blocked_gate"),
    [
        ("skip", "authenticated_https_private_s3"),
        ("stale-release", "target_configuration"),
        ("tamper-artifact", "immutable_infrastructure_plan"),
        ("path-traversal", "cost_and_budget_approval"),
        ("expired", "operations_rehearsal"),
    ],
)
def test_release_gate_blocks_bad_or_stale_evidence(
    tmp_path: Path, mutation: str, blocked_gate: str
) -> None:
    manifest = _bundle(tmp_path)
    data = json.loads(manifest.read_text())
    evidence_path = tmp_path / data["gates"][blocked_gate]
    evidence = json.loads(evidence_path.read_text())
    if mutation == "skip":
        evidence["tests"]["skipped"] = 1
        evidence["tests"]["passed"] -= 1
    elif mutation == "stale-release":
        evidence["release"]["build_sha256"] = "f" * 64
    elif mutation == "tamper-artifact":
        (tmp_path / "artifacts" / "proof.txt").write_text("modified")
    elif mutation == "path-traversal":
        evidence["artifact_path"] = "../../outside.txt"
    elif mutation == "expired":
        evidence["verified_at_utc"] = "2020-01-01T00:00:00Z"
    _write_json(evidence_path, evidence)

    report = evaluate_manifest(
        manifest,
        current_release=RELEASE,
        expected_context_configurations=_expected_configs(),
        validate_dsql_runtime=False,
    )

    assert report["result"] == "blocked"
    assert blocked_gate in report["blocked_gates"]


def test_release_gate_rejects_missing_gate_inventory(tmp_path: Path) -> None:
    manifest = _bundle(tmp_path)
    data = json.loads(manifest.read_text())
    del data["gates"]["encrypted_cloud_recovery"]
    _write_json(manifest, data)

    with pytest.raises(GateError, match="entries are missing"):
        evaluate_manifest(
            manifest,
            current_release=RELEASE,
            expected_context_configurations=_expected_configs(),
            validate_dsql_runtime=False,
        )


def test_release_gate_requires_independent_well_formed_target_configs(
    tmp_path: Path,
) -> None:
    manifest = _bundle(tmp_path)
    with pytest.raises(GateError, match="Independent current target"):
        evaluate_manifest(
            manifest, current_release=RELEASE, validate_dsql_runtime=False
        )
    with pytest.raises(GateError, match="incomplete or malformed"):
        evaluate_manifest(
            manifest,
            current_release=RELEASE,
            expected_context_configurations=[],  # type: ignore[arg-type]
            validate_dsql_runtime=False,
        )


def test_dsql_skip_and_missing_matrix_evidence_block_release(
    tmp_path: Path,
) -> None:
    manifest = _bundle(tmp_path)
    data = json.loads(manifest.read_text())
    dsql_path = tmp_path / data["gates"]["real_dsql_release_suite"]
    evidence = json.loads(dsql_path.read_text())
    evidence["tests"]["skipped"] = 1
    evidence["tests"]["passed"] -= 1
    evidence["unverified_release_gates"] = ["mid_migration_interruption_resume"]
    _write_json(dsql_path, evidence)

    report = evaluate_manifest(
        manifest,
        current_release=RELEASE,
        expected_context_configurations=_expected_configs(),
        validate_dsql_runtime=False,
    )

    assert report["result"] == "blocked"
    assert "real_dsql_release_suite" in report["blocked_gates"]


def test_different_configuration_hash_within_one_context_blocks(
    tmp_path: Path,
) -> None:
    manifest = _bundle(tmp_path)
    data = json.loads(manifest.read_text())
    evidence_path = tmp_path / data["gates"]["cost_and_budget_approval"]
    evidence = json.loads(evidence_path.read_text())
    evidence["environment_configuration_sha256"] = "f" * 64
    _write_json(evidence_path, evidence)

    report = evaluate_manifest(
        manifest,
        current_release=RELEASE,
        expected_context_configurations=_expected_configs(),
        validate_dsql_runtime=False,
    )

    assert report["result"] == "blocked"
    assert "cost_and_budget_approval" in report["blocked_gates"]


def test_unanimous_stale_production_configuration_cannot_pass(tmp_path: Path) -> None:
    manifest = _bundle(tmp_path)
    data = json.loads(manifest.read_text())
    old_hash = "f" * 64
    for gate_id, relative in data["gates"].items():
        path = tmp_path / relative
        evidence = json.loads(path.read_text())
        if gate_id == "real_dsql_release_suite":
            evidence["configuration_sha256"] = CONTEXTS["dsql_test"]
        else:
            context = evidence["configuration_context"]
            if context == "production":
                evidence["environment_configuration_sha256"] = old_hash
        _write_json(path, evidence)

    report = evaluate_manifest(
        manifest,
        current_release=RELEASE,
        expected_context_configurations=_expected_configs(),
        validate_dsql_runtime=False,
    )
    assert report["result"] == "blocked"
    assert "target_configuration" in report["blocked_gates"]


def test_gate_does_not_accept_empty_or_boolean_test_counts() -> None:
    from app.release.stage4_gate import _validate_tests

    with pytest.raises(GateError):
        _validate_tests(
            {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
        )
    with pytest.raises(GateError):
        _validate_tests(
            {"tests": True, "passed": True, "failed": 0, "errors": 0, "skipped": 0}
        )
