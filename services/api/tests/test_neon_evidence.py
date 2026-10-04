"""Offline guardrails for the real-Neon evidence and promotion gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.release import neon_evidence
from app.release.neon_evidence import (
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
    build, schema, fixtures = neon_evidence._source_paths()
    root = neon_evidence.REPOSITORY_ROOT
    for relative in ("services/api/alembic.ini", "services/api/alembic/env.py"):
        assert root / relative in build
        assert root / relative in schema
    assert root / "fixtures/stage-5/synthetic-research-evaluation.json" in fixtures
    assert root / "tests/infra/test_infra_contract.py" in fixtures


def test_fixture_edits_invalidate_release_fingerprint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(neon_evidence, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(neon_evidence, "API_ROOT", tmp_path / "services/api")
    fixture = tmp_path / "fixtures/synthetic.json"
    fixture.parent.mkdir()
    fixture.write_text('{"expected": 1}')
    for paths in neon_evidence._source_paths():
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
        "suite": "neon-postgres-stage4-release",
        "result": "passed",
        "backend": "postgres",
        "fixture_version": FIXTURE_VERSION,
        **_fingerprints(),
        "git_commit": "0" * 40,
        "image_digest": "sha256:" + "3" * 64,
        "database_identity_sha256": "1" * 64,
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
        "suite": "neon-postgres-stage4-release",
        "result": "passed",
        "backend": "postgres",
        "fixture_version": FIXTURE_VERSION,
        **_fingerprints(),
        "git_commit": "0" * 40,
        "image_digest": "sha256:" + "3" * 64,
        "database_identity_sha256": "1" * 64,
        "configuration_sha256": "2" * 64,
        "tests": {"tests": 13, "passed": 13, "failed": 0, "errors": 0, "skipped": 0},
        "executed_cases": sorted(REQUIRED_CASES),
        "missing_required_cases": [],
        "unverified_release_gates": ["pooled_idle_reconnect"],
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
        "backend": "postgres",
        "fixture_version": FIXTURE_VERSION,
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence))
    with pytest.raises(EvidenceError, match="required Stage 4 suite"):
        validate_evidence(path)


def test_promotion_gate_rejects_stale_schema_fingerprint(tmp_path: Path) -> None:
    evidence = {
        "evidence_version": 1,
        "suite": "neon-postgres-stage4-release",
        "result": "passed",
        "backend": "postgres",
        "fixture_version": FIXTURE_VERSION,
        **_fingerprints(),
        "git_commit": "0" * 40,
        "image_digest": "sha256:" + "3" * 64,
        "database_identity_sha256": "1" * 64,
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


def test_configuration_fingerprint_binds_neon_target_and_runtime_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    original = _configuration_fingerprint()

    monkeypatch.setenv("GCP_PROJECT", "synthetic-target")
    changed_endpoint = _configuration_fingerprint()
    monkeypatch.delenv("GCP_PROJECT")
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


def test_connection_configuration_is_keyed_and_changes_invalidate_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    for key in (
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "NEON_TEST_DATABASE_URL",
        "NEON_TEST_MIGRATION_DATABASE_URL",
        "EVIDENCE_CONFIGURATION_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:private-value@fixture/db")
    with pytest.raises(EvidenceError, match="EVIDENCE_CONFIGURATION_KEY"):
        _configuration_fingerprint()
    monkeypatch.setenv("EVIDENCE_CONFIGURATION_KEY", "k" * 32)
    first = _configuration_fingerprint()
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:changed-value@fixture/db")
    assert _configuration_fingerprint() != first
    assert "private-value" not in first
