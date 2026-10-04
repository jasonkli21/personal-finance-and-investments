"""Validate explicit database backend and bounded connection settings."""

import pytest

from app.config import load_settings


def clear_database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DATABASE_BACKEND",
        "DEMO_MODE",
        "PERSONAL_AI_ENABLED",
        "DATABASE_URL",
        "MIGRATION_DATABASE_URL",
        "CLOUD_RUN_JOB",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_NAME",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW",
        "DATABASE_POOL_RECYCLE_SECONDS",
        "DATABASE_CONNECT_TIMEOUT_SECONDS",
        "APP_ENV",
        "APP_PUBLIC_ORIGIN",
        "FILE_STORAGE_BACKEND",
        "PRIVATE_GCS_BUCKET",
        "GCP_PROJECT",
        "MAX_PRIVATE_FILE_BYTES",
        "MAX_IMPORT_FILE_BYTES",
        "MAX_IMPORT_ROWS",
        "MAX_PDF_PAGES",
        "PDF_PARSER_TIMEOUT_SECONDS",
        "JOB_LEASE_SECONDS",
        "JOB_MAX_ATTEMPTS",
        "AUTH_ENABLED",
        "AUTH_ISSUER_URL",
        "AUTH_CLIENT_ID",
        "AUTH_CLIENT_SECRET",
        "AUTH_SESSION_SIGNING_KEY",
        "AUTH_ALLOWED_SUBJECT",
        "AUTH_PERSONAL_SCOPE_ID",
        "AUTH_SESSION_TTL_SECONDS",
        "AUTH_COOKIE_SECURE",
        "JOB_WORKER_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


def test_unknown_database_backend_fails_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_BACKEND", "mysql")

    with pytest.raises(ValueError, match="DATABASE_BACKEND"):
        load_settings()


def test_demo_mode_requires_explicit_local_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    settings = load_settings()
    assert settings.demo_mode is False

    monkeypatch.setenv("DEMO_MODE", "true")
    assert load_settings().demo_mode is True

    monkeypatch.setenv("DATABASE_BACKEND", "mysql")
    with pytest.raises(ValueError, match="DATABASE_BACKEND"):
        load_settings()


def test_demo_mode_rejects_database_url_and_nonlocal_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://remote.example/portfolio")
    with pytest.raises(ValueError, match="discrete local database"):
        load_settings()

    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.setenv("DATABASE_HOST", "remote.example")
    with pytest.raises(ValueError, match="loopback or Compose"):
        load_settings()


def test_stage4_bounded_request_settings_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    settings = {
        "MAX_PRIVATE_FILE_BYTES": "20000000",
        "MAX_IMPORT_FILE_BYTES": "5000000",
        "MAX_IMPORT_ROWS": "1000",
        "MAX_PDF_PAGES": "40",
        "PDF_PARSER_TIMEOUT_SECONDS": "8",
        "JOB_MAX_ATTEMPTS": "3",
        "JOB_WORKER_ENABLED": "false",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)

    loaded = load_settings()

    assert loaded.max_private_file_bytes == 20_000_000
    assert loaded.max_import_file_bytes == 5_000_000
    assert loaded.max_import_rows == 1000
    assert loaded.max_pdf_pages == 40
    assert loaded.pdf_parser_timeout_seconds == 8
    assert loaded.job_max_attempts == 3
    assert loaded.job_worker_enabled is False


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("MAX_PRIVATE_FILE_BYTES", "100000001"),
        ("MAX_IMPORT_FILE_BYTES", "20000001"),
        ("MAX_IMPORT_ROWS", "20001"),
        ("MAX_PDF_PAGES", "101"),
        ("PDF_PARSER_TIMEOUT_SECONDS", "31"),
        ("JOB_MAX_ATTEMPTS", "9"),
    ],
)
def test_stage4_request_settings_reject_unbounded_values(
    monkeypatch: pytest.MonkeyPatch, setting: str, value: str
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv(setting, value)

    with pytest.raises(ValueError, match=setting):
        load_settings()


def test_connection_fields_keep_reserved_password_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("POSTGRES_USER", "portfolio-user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:/?#% word")
    monkeypatch.setenv("POSTGRES_DB", "portfolio-db")

    settings = load_settings()

    assert settings.database_url is None
    assert settings.database_host == "127.0.0.1"
    assert settings.database_port == 5432
    assert settings.database_user == "portfolio-user"
    assert settings.database_password == "p@ss:/?#% word"
    assert settings.database_name == "portfolio-db"


def test_nonempty_database_url_is_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://explicit-host/explicit-db")
    monkeypatch.setenv("DATABASE_HOST", "ignored-host")

    settings = load_settings()

    assert settings.database_url == "postgresql://explicit-host/explicit-db"
    assert settings.database_host == "ignored-host"


def test_pool_bounds_are_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_POOL_SIZE", "40")

    with pytest.raises(ValueError, match="DATABASE_POOL_SIZE"):
        load_settings()


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_invalid_database_port_fails_configuration(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_PORT", value)

    with pytest.raises(ValueError, match="DATABASE_PORT"):
        load_settings()


def test_explicit_database_port_takes_precedence_over_invalid_compose_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_PORT", "5433")
    monkeypatch.setenv("POSTGRES_PORT", "invalid")
    assert load_settings().database_port == 5433
    monkeypatch.delenv("DATABASE_PORT")
    with pytest.raises(ValueError, match="DATABASE_PORT must be an integer"):
        load_settings()


def configure_valid_production(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_database_env(monkeypatch)
    for key in (
        "APP_ENV",
        "APP_PUBLIC_ORIGIN",
        "FILE_STORAGE_BACKEND",
        "PRIVATE_GCS_BUCKET",
        "AUTH_ENABLED",
        "AUTH_ISSUER_URL",
        "AUTH_CLIENT_ID",
        "AUTH_CLIENT_SECRET",
        "AUTH_SESSION_SIGNING_KEY",
        "AUTH_ALLOWED_SUBJECT",
        "AUTH_PERSONAL_SCOPE_ID",
        "AUTH_COOKIE_SECURE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_PUBLIC_ORIGIN", "https://finance.example.test")
    monkeypatch.setenv("FILE_STORAGE_BACKEND", "gcs")
    monkeypatch.setenv("PRIVATE_GCS_BUCKET", "finance-private-example")
    monkeypatch.setenv("GCP_PROJECT", "finance-static-example")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_ISSUER_URL", "https://identity.example.test")
    monkeypatch.setenv("AUTH_CLIENT_ID", "finance-client")
    monkeypatch.setenv("AUTH_CLIENT_SECRET", "synthetic-client-secret")
    monkeypatch.setenv(
        "AUTH_SESSION_SIGNING_KEY", "synthetic-signing-key-that-is-long-enough"
    )
    monkeypatch.setenv("AUTH_ALLOWED_SUBJECT", "local-owner")
    monkeypatch.setenv("AUTH_PERSONAL_SCOPE_ID", "personal-finance")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    monkeypatch.setenv("DATABASE_BACKEND", "postgres")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://finance:synthetic@ep-fixture.us-central1.gcp.neon.tech/neondb?sslmode=verify-full&sslrootcert=system",
    )
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")


def test_production_requires_private_authenticated_neon_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(ValueError, match="AUTH_ENABLED"):
        load_settings()

    configure_valid_production(monkeypatch)
    settings = load_settings()
    assert settings.app_env == "production"
    assert settings.database_backend == "postgres"
    assert settings.file_storage_backend == "gcs"
    assert settings.auth_enabled is True
    assert settings.auth_cookie_secure is True


def test_production_worker_flag_uses_one_fail_closed_effective_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_valid_production(monkeypatch)
    monkeypatch.delenv("JOB_WORKER_ENABLED")
    assert load_settings().job_worker_enabled is False
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    assert load_settings().job_worker_enabled is False
    monkeypatch.setenv("JOB_WORKER_ENABLED", "true")
    with pytest.raises(ValueError, match="bounded Cloud Run Job"):
        load_settings()
    monkeypatch.setenv("JOB_WORKER_ENABLED", "sometimes")
    with pytest.raises(ValueError, match="must be 'true' or 'false'"):
        load_settings()


def test_import_file_limit_cannot_exceed_private_object_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("MAX_PRIVATE_FILE_BYTES", "1024")
    monkeypatch.setenv("MAX_IMPORT_FILE_BYTES", "2048")
    with pytest.raises(ValueError, match="cannot exceed"):
        load_settings()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("AUTH_ISSUER_URL", "http://identity.example.test", "HTTPS issuer"),
        ("AUTH_SESSION_SIGNING_KEY", "too-short", "at least 32 characters"),
    ],
)
def test_production_requires_secure_oidc_settings(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, message: str
) -> None:
    configure_valid_production(monkeypatch)
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=message):
        load_settings()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("AUTH_COOKIE_SECURE", "false", "Secure"),
        ("DATABASE_URL", "", "DATABASE_URL"),
        ("FILE_STORAGE_BACKEND", "local", "private GCS"),
        ("GCP_PROJECT", "", "GCP_PROJECT"),
        ("JOB_WORKER_ENABLED", "true", "bounded Cloud Run Job"),
        ("DEMO_MODE", "true", "DEMO_MODE"),
    ],
)
def test_production_rejects_unsafe_runtime_modes(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str, message: str
) -> None:
    configure_valid_production(monkeypatch)
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=message):
        load_settings()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:secret@localhost/db?sslmode=verify-full&sslrootcert=system",
        "postgresql://user:secret@ep-fixture.gcp.neon.tech/db?sslmode=require",
        "sqlite:///private.db",
        "postgresql://user:secret@ep-fixture.gcp.neon.tech/db?sslmode=verify-full&sslrootcert=system&host=localhost",
        "postgresql://user:secret@ep-fixture.gcp.neon.tech/db?sslmode=verify-full&sslrootcert=system&service=override",
    ],
)
def test_production_database_requires_verified_neon_tls(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    configure_valid_production(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        load_settings()


def test_migration_url_is_independently_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_valid_production(monkeypatch)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://secret@remote/db")
    with pytest.raises(ValueError, match="MIGRATION_DATABASE_URL"):
        load_settings()
