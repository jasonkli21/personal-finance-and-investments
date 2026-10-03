"""Offline guardrails for the real-DSQL evidence and promotion gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.release import dsql_evidence
from app.release.dsql_evidence import (
    CONFIG_KEYS,
    FIXTURE_VERSION,
    REQUIRED_CASES,
    EvidenceError,
    _configuration_fingerprint,
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


def test_evidence_binds_migration_runtime_and_synthetic_fixture_files() -> None:
    build, schema, fixtures = dsql_evidence._source_paths()
    root = dsql_evidence.REPOSITORY_ROOT
    for relative in ("services/api/alembic.ini", "services/api/alembic/env.py"):
        assert root / relative in build
        assert root / relative in schema
    assert root / "fixtures/stage-5/synthetic-research-evaluation.json" in fixtures
    assert root / "tests/infra/test_infra_contract.py" in fixtures


def test_fixture_edits_invalidate_release_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dsql_evidence, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(dsql_evidence, "API_ROOT", tmp_path / "services/api")
    fixture = tmp_path / "fixtures/synthetic.json"
    fixture.parent.mkdir()
    fixture.write_text('{"expected": 1}')
    for paths in dsql_evidence._source_paths():
        for path in paths:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic file")
    before = _fingerprints()
    fixture.write_text('{"expected": 2}')
    after = _fingerprints()
    assert before["fixture_sha256"] != after["fixture_sha256"]


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
    assert len(REQUIRED_CASES) == 13
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
        "tests": {"tests": 13, "passed": 13, "failed": 0, "errors": 0, "skipped": 0},
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


def test_promotion_gate_rejects_unrecognized_suite_identity(tmp_path: Path) -> None:
    evidence = {
        "evidence_version": 1,
        "suite": "operator-supplied-wrapper",
        "result": "passed",
        "backend": "aurora_dsql",
        "fixture_version": FIXTURE_VERSION,
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(EvidenceError, match="required Stage 4 suite"):
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


def test_configuration_fingerprint_hmac_binds_owner_scope_without_recording_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SESSION_SIGNING_KEY", "s" * 48)
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("AUTH_ALLOWED_SUBJECT", "private-subject-value")
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", "private-scope-value")

    original = _configuration_fingerprint()
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", "another-private-scope")
    changed_scope = _configuration_fingerprint()
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", "private-scope-value")
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "another-private-client-secret")
    changed_client_secret = _configuration_fingerprint()
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("AUTH_SESSION_SIGNING_KEY", "r" * 48)
    changed_key = _configuration_fingerprint()

    assert original != changed_scope
    assert original != changed_client_secret
    assert original != changed_key
    assert "private-subject-value" not in original
    assert "private-scope-value" not in original
    assert "private-client-secret" not in original


def test_configuration_fingerprint_binds_dsql_target_and_runtime_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    original = _configuration_fingerprint()

    monkeypatch.setenv(
        "AURORA_DSQL_CLUSTER_ENDPOINT", "cluster-a.dsql.us-east-1.on.aws"
    )
    changed_endpoint = _configuration_fingerprint()
    monkeypatch.delenv("AURORA_DSQL_CLUSTER_ENDPOINT")
    monkeypatch.setenv("JOB_LEASE_SECONDS", "60")
    changed_lease = _configuration_fingerprint()

    assert original != changed_endpoint
    assert original != changed_lease


def test_enabled_auth_cannot_create_evidence_without_identity_fingerprint_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.delenv("AUTH_SESSION_SIGNING_KEY", raising=False)
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "private-client-secret")
    monkeypatch.setenv("AUTH_ALLOWED_SUBJECT", "subject")
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", "scope")

    with pytest.raises(EvidenceError, match="requires a signing key"):
        _configuration_fingerprint()


def test_enabled_auth_evidence_requires_oidc_client_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_SESSION_SIGNING_KEY", "s" * 48)
    monkeypatch.delenv("AUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("AUTH_ALLOWED_SUBJECT", "subject")
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", "scope")

    with pytest.raises(EvidenceError, match="OIDC secret"):
        _configuration_fingerprint()
