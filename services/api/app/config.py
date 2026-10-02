"""Minimal Stage 0 configuration; DSQL connection work belongs to Stage 0.4."""

from dataclasses import dataclass
from os import environ


@dataclass(frozen=True)
class Settings:
    database_backend: str
    database_url: str | None
    database_host: str
    database_port: int
    database_user: str
    database_password: str
    database_name: str


def load_settings() -> Settings:
    backend = environ.get("DATABASE_BACKEND", "postgres")
    if backend != "postgres":
        raise ValueError(
            f"DATABASE_BACKEND={backend!r} is unsupported in Stage 0.1; "
            "Aurora DSQL support is planned for Stage 0.4"
        )

    try:
        database_port = int(
            environ.get("DATABASE_PORT", environ.get("POSTGRES_PORT", "5432"))
        )
    except ValueError as exc:
        raise ValueError(
            "DATABASE_PORT must be an integer between 1 and 65535"
        ) from exc
    if not 1 <= database_port <= 65535:
        raise ValueError("DATABASE_PORT must be an integer between 1 and 65535")

    # DATABASE_URL is an explicit override. Otherwise use separate connection
    # fields so passwords containing URL-reserved characters remain unambiguous.
    database_url = environ.get("DATABASE_URL") or None
    return Settings(
        database_backend=backend,
        database_url=database_url,
        database_host=environ.get("DATABASE_HOST", "127.0.0.1"),
        database_port=database_port,
        database_user=environ.get(
            "DATABASE_USER", environ.get("POSTGRES_USER", "portfolio")
        ),
        database_password=environ.get(
            "DATABASE_PASSWORD",
            environ.get("POSTGRES_PASSWORD", "local-only-change-me"),
        ),
        database_name=environ.get(
            "DATABASE_NAME", environ.get("POSTGRES_DB", "portfolio")
        ),
    )
