"""Validated local/DSQL configuration and disabled personal-AI integration."""

from dataclasses import dataclass
from os import environ


def _int_setting(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw_value = environ.get(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer between {minimum} and {maximum}"
        ) from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    database_backend: str
    demo_mode: bool
    database_url: str | None
    database_host: str
    database_port: int
    database_user: str
    database_password: str
    database_name: str
    aws_region: str | None
    aurora_dsql_cluster_endpoint: str | None
    aurora_dsql_db_user: str | None
    aurora_dsql_migration_db_user: str | None
    database_pool_size: int
    database_max_overflow: int
    database_pool_recycle_seconds: int
    database_connect_timeout_seconds: int
    private_file_dir: str
    max_import_file_bytes: int
    max_import_rows: int
    max_pdf_pages: int
    pdf_parser_timeout_seconds: int
    personal_ai_enabled: bool


def load_settings() -> Settings:
    personal_ai_raw = environ.get("PERSONAL_AI_ENABLED", "false").casefold()
    if personal_ai_raw not in {"true", "false"}:
        raise ValueError("PERSONAL_AI_ENABLED must be 'true' or 'false'")
    if personal_ai_raw == "true":
        raise ValueError(
            "PERSONAL_AI_ENABLED cannot be enabled: transport contract, "
            "authentication/service authorization and data-handling review "
            "are not implemented"
        )
    backend = environ.get("DATABASE_BACKEND", "postgres")
    if backend not in {"postgres", "aurora_dsql"}:
        raise ValueError("DATABASE_BACKEND must be 'postgres' or 'aurora_dsql'")

    database_url = environ.get("DATABASE_URL") or None
    demo_mode_raw = environ.get("DEMO_MODE", "false").casefold()
    if demo_mode_raw not in {"true", "false"}:
        raise ValueError("DEMO_MODE must be 'true' or 'false'")
    demo_mode = demo_mode_raw == "true"
    database_host = environ.get("DATABASE_HOST", "127.0.0.1")
    if demo_mode:
        if backend != "postgres":
            raise ValueError("DEMO_MODE is available only with local PostgreSQL")
        if database_url is not None:
            raise ValueError("DEMO_MODE requires discrete local database settings")
        if database_host not in {"127.0.0.1", "localhost", "::1", "db"}:
            raise ValueError("DEMO_MODE only allows loopback or Compose database hosts")
    database_port = _int_setting(
        "DATABASE_PORT",
        int(environ.get("POSTGRES_PORT", "5432")),
        minimum=1,
        maximum=65535,
    )
    pool_size = _int_setting("DATABASE_POOL_SIZE", 5, minimum=1, maximum=20)
    max_overflow = _int_setting("DATABASE_MAX_OVERFLOW", 5, minimum=0, maximum=20)
    if pool_size + max_overflow > 40:
        raise ValueError(
            "DATABASE_POOL_SIZE plus DATABASE_MAX_OVERFLOW must not exceed 40"
        )

    aws_region = environ.get("AWS_REGION") or None
    cluster_endpoint = environ.get("AURORA_DSQL_CLUSTER_ENDPOINT") or None
    dsql_user = environ.get("AURORA_DSQL_DB_USER") or None
    migration_user = environ.get("AURORA_DSQL_MIGRATION_DB_USER") or None
    if backend == "aurora_dsql":
        if database_url is not None:
            raise ValueError(
                "DATABASE_URL is not supported for Aurora DSQL; "
                "use IAM connector settings"
            )
        required = {
            "AWS_REGION": aws_region,
            "AURORA_DSQL_CLUSTER_ENDPOINT": cluster_endpoint,
            "AURORA_DSQL_DB_USER": dsql_user,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                f"Aurora DSQL configuration is missing: {', '.join(missing)}"
            )
        if dsql_user is not None and dsql_user.casefold() == "admin":
            raise ValueError("AURORA_DSQL_DB_USER must be a scoped application role")
        if migration_user is not None and migration_user == dsql_user:
            raise ValueError(
                "AURORA_DSQL_MIGRATION_DB_USER must differ from the application role"
            )

    return Settings(
        personal_ai_enabled=False,
        database_backend=backend,
        demo_mode=demo_mode,
        database_url=database_url,
        database_host=database_host,
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
        aws_region=aws_region,
        aurora_dsql_cluster_endpoint=cluster_endpoint,
        aurora_dsql_db_user=dsql_user,
        aurora_dsql_migration_db_user=migration_user,
        database_pool_size=pool_size,
        database_max_overflow=max_overflow,
        database_pool_recycle_seconds=_int_setting(
            "DATABASE_POOL_RECYCLE_SECONDS", 3000, minimum=60, maximum=3500
        ),
        database_connect_timeout_seconds=_int_setting(
            "DATABASE_CONNECT_TIMEOUT_SECONDS", 3, minimum=1, maximum=30
        ),
        private_file_dir=environ.get("PRIVATE_FILE_DIR", "./.private"),
        max_import_file_bytes=_int_setting(
            "MAX_IMPORT_FILE_BYTES", 5_000_000, minimum=1024, maximum=20_000_000
        ),
        max_import_rows=_int_setting(
            "MAX_IMPORT_ROWS", 5000, minimum=1, maximum=20_000
        ),
        max_pdf_pages=_int_setting("MAX_PDF_PAGES", 40, minimum=1, maximum=100),
        pdf_parser_timeout_seconds=_int_setting(
            "PDF_PARSER_TIMEOUT_SECONDS", 8, minimum=1, maximum=30
        ),
    )
