"""Validate explicit database backend and bounded connection settings."""

import pytest

from app.config import load_settings


def clear_database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DATABASE_BACKEND",
        "DEMO_MODE",
        "PERSONAL_AI_ENABLED",
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_NAME",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "AWS_REGION",
        "AURORA_DSQL_CLUSTER_ENDPOINT",
        "AURORA_DSQL_DB_USER",
        "AURORA_DSQL_MIGRATION_DB_USER",
        "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW",
        "DATABASE_POOL_RECYCLE_SECONDS",
        "DATABASE_CONNECT_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_dsql_backend_is_explicitly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    with pytest.raises(ValueError, match="AURORA_DSQL_CLUSTER_ENDPOINT"):
        load_settings()


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

    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    with pytest.raises(ValueError, match="local PostgreSQL"):
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


def test_dsql_requires_scoped_application_and_distinct_migration_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AURORA_DSQL_CLUSTER_ENDPOINT", "cluster.dsql.us-east-1.on.aws")
    monkeypatch.setenv("AURORA_DSQL_DB_USER", "portfolio_app")
    monkeypatch.setenv("AURORA_DSQL_MIGRATION_DB_USER", "portfolio_app")

    with pytest.raises(ValueError, match="must differ"):
        load_settings()


def test_dsql_rejects_password_bearing_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AURORA_DSQL_CLUSTER_ENDPOINT", "cluster.dsql.us-east-1.on.aws")
    monkeypatch.setenv("AURORA_DSQL_DB_USER", "portfolio_app")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@example/db")

    with pytest.raises(ValueError, match="DATABASE_URL"):
        load_settings()


@pytest.mark.parametrize("value", ["admin", "ADMIN"])
def test_dsql_rejects_admin_application_role(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AURORA_DSQL_CLUSTER_ENDPOINT", "cluster.dsql.us-east-1.on.aws")
    monkeypatch.setenv("AURORA_DSQL_DB_USER", value)

    with pytest.raises(ValueError, match="scoped application role"):
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
