"""Offline guardrails for the real-DSQL evidence and promotion gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.release.dsql_evidence import (
    FIXTURE_VERSION,
    REQUIRED_CASES,
    EvidenceError,
    _fingerprints,
    _parse_junit,
    validate_evidence,
)


def test_junit_summary_counts_skips_as_nonpassing(tmp_path: Path) -> None:
    junit = tmp_path / "results.xml"
    junit.write_text(
        '<testsuites tests="2" failures="0" errors="0" skipped="1">'
        '<testsuite tests="2" failures="0" errors="0" skipped="1">'
        '<testcase classname="test_a" name="passed"/>'
        '<testcase classname="test_a" name="skipped"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )

    counts, cases = _parse_junit(junit)

    assert counts == {"tests": 2, "passed": 1, "failed": 0, "errors": 0, "skipped": 1}
    assert cases == {"passed", "skipped"}


def test_promotion_gate_rejects_skipped_real_cluster_suite(tmp_path: Path) -> None:
    evidence = {
        "evidence_version": 1,
        "suite": "aurora-dsql-stage4-release",
        "result": "passed",
        "backend": "aurora_dsql",
        "fixture_version": FIXTURE_VERSION,
        **_fingerprints(),
        "git_commit": "0" * 40,
        "image_digest": "sha256:" + "3" * 64,
        "cluster_identity_sha256": "1" * 64,
        "configuration_sha256": "2" * 64,
        "tests": {"tests": 9, "passed": 9, "failed": 0, "errors": 0, "skipped": 1},
        "executed_cases": sorted(REQUIRED_CASES),
        "missing_required_cases": [],
        "credentials_recorded": False,
        "raw_junit_recorded": False,
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence))

    with pytest.raises(EvidenceError, match="skipped"):
        validate_evidence(path)


def test_promotion_gate_rejects_incomplete_live_matrix(tmp_path: Path) -> None:
    assert len(REQUIRED_CASES) == 9
    evidence = {
        "evidence_version": 1,
        "result": "passed",
        "backend": "aurora_dsql",
        "fixture_version": FIXTURE_VERSION,
        **_fingerprints(),
        "git_commit": "0" * 40,
        "image_digest": "sha256:" + "3" * 64,
        "cluster_identity_sha256": "1" * 64,
        "configuration_sha256": "2" * 64,
        "tests": {"tests": 9, "passed": 9, "failed": 0, "errors": 0, "skipped": 0},
        "executed_cases": sorted(REQUIRED_CASES),
        "missing_required_cases": [],
        "unverified_release_gates": ["iam_token_expiry_reconnect_after_15_minutes"],
        "credentials_recorded": False,
        "raw_junit_recorded": False,
    }
    path = tmp_path / "incomplete.json"
    path.write_text(json.dumps(evidence))

    with pytest.raises(EvidenceError, match="matrix evidence is still outstanding"):
        validate_evidence(path)


def test_promotion_gate_rejects_stale_schema_fingerprint(tmp_path: Path) -> None:
    evidence = {
        "evidence_version": 1,
        "suite": "aurora-dsql-stage4-release",
        "result": "passed",
        "backend": "aurora_dsql",
        "fixture_version": FIXTURE_VERSION,
        **_fingerprints(),
        "git_commit": "0" * 40,
        "image_digest": "sha256:" + "3" * 64,
        "cluster_identity_sha256": "1" * 64,
        "configuration_sha256": "2" * 64,
        "tests": {"tests": 9, "passed": 9, "failed": 0, "errors": 0, "skipped": 0},
        "executed_cases": sorted(REQUIRED_CASES),
        "missing_required_cases": [],
        "unverified_release_gates": [],
        "credentials_recorded": False,
        "raw_junit_recorded": False,
    }
    evidence["schema_sha256"] = "f" * 64
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(evidence))

    with pytest.raises(EvidenceError, match="schema_sha256 changed"):
        validate_evidence(path)
