"""Keep unimplemented cloud configuration from silently using local PostgreSQL."""

import pytest

from app.config import load_settings


def clear_database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DATABASE_BACKEND",
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
    ):
        monkeypatch.delenv(key, raising=False)


def test_dsql_backend_is_explicitly_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_BACKEND", "aurora_dsql")
    with pytest.raises(ValueError, match="Stage 0.4"):
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


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_invalid_database_port_fails_configuration(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    clear_database_env(monkeypatch)
    monkeypatch.setenv("DATABASE_PORT", value)

    with pytest.raises(ValueError, match="DATABASE_PORT"):
        load_settings()
