"""Validated PostgreSQL/GCP configuration and disabled personal-AI integration."""

import re
from dataclasses import dataclass
from os import environ
from urllib.parse import urlsplit


def _int_setting(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    fallback_env: str | None = None,
) -> int:
    raw_value = environ.get(name)
    if raw_value is None:
        raw_value = (
            environ.get(fallback_env, str(default))
            if fallback_env is not None
            else str(default)
        )
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
    app_env: str
    app_public_origin: str | None
    database_backend: str
    demo_mode: bool
    database_url: str | None
    database_host: str
    database_port: int
    database_user: str
    database_password: str
    database_name: str
    migration_database_url: str | None
    gcp_project: str | None
    cloud_run_job: str | None
    database_pool_size: int
    database_max_overflow: int
    database_pool_recycle_seconds: int
    database_connect_timeout_seconds: int
    private_file_dir: str
    file_storage_backend: str
    private_gcs_bucket: str | None
    max_private_file_bytes: int
    max_import_file_bytes: int
    max_import_rows: int
    max_pdf_pages: int
    pdf_parser_timeout_seconds: int
    job_worker_enabled: bool
    job_poll_interval_seconds: int
    job_lease_seconds: int
    job_max_attempts: int
    personal_ai_enabled: bool
    auth_enabled: bool
    auth_issuer_url: str | None
    auth_client_id: str | None
    auth_client_secret: str | None
    auth_session_signing_key: str | None
    auth_allowed_subject: str | None
    auth_personal_scope_id: str | None
    auth_session_ttl_seconds: int
    auth_cookie_secure: bool


def load_settings() -> Settings:
    app_env = environ.get("APP_ENV", "development").casefold()
    if app_env not in {"development", "test", "production"}:
        raise ValueError("APP_ENV must be development, test or production")
    worker_raw = environ.get(
        "JOB_WORKER_ENABLED", "false" if app_env == "production" else "true"
    ).casefold()
    if worker_raw not in {"true", "false"}:
        raise ValueError("JOB_WORKER_ENABLED must be 'true' or 'false'")
    auth_raw = environ.get("AUTH_ENABLED", "false").casefold()
    if auth_raw not in {"true", "false"}:
        raise ValueError("AUTH_ENABLED must be 'true' or 'false'")
    auth_enabled = auth_raw == "true"
    public_origin = environ.get("APP_PUBLIC_ORIGIN") or None
    storage_backend = environ.get("FILE_STORAGE_BACKEND", "local").casefold()
    if storage_backend not in {"local", "gcs"}:
        raise ValueError("FILE_STORAGE_BACKEND must be 'local' or 'gcs'")
    private_bucket = environ.get("PRIVATE_GCS_BUCKET") or None
    gcp_project = environ.get("GCP_PROJECT") or None
    cloud_run_job = environ.get("CLOUD_RUN_JOB") or None
    if storage_backend == "gcs" and (
        not private_bucket
        or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", private_bucket)
    ):
        raise ValueError("GCS storage requires a DNS-safe PRIVATE_GCS_BUCKET")
    if cloud_run_job and not re.fullmatch(
        r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z0-9-]+/jobs/[a-z][a-z0-9-]{0,62}",
        cloud_run_job,
    ):
        raise ValueError("CLOUD_RUN_JOB must be a full job resource name")
    auth_issuer_url = environ.get("AUTH_ISSUER_URL") or None
    auth_client_id = environ.get("AUTH_CLIENT_ID") or None
    auth_client_secret = environ.get("AUTH_CLIENT_SECRET") or None
    auth_session_signing_key = environ.get("AUTH_SESSION_SIGNING_KEY") or None
    auth_subject = environ.get("AUTH_ALLOWED_SUBJECT") or None
    auth_scope_id = environ.get("AUTH_PERSONAL_SCOPE_ID") or None
    cookie_secure_raw = environ.get(
        "AUTH_COOKIE_SECURE", "true" if app_env == "production" else "false"
    ).casefold()
    if cookie_secure_raw not in {"true", "false"}:
        raise ValueError("AUTH_COOKIE_SECURE must be 'true' or 'false'")
    cookie_secure = cookie_secure_raw == "true"
    session_ttl = _int_setting(
        "AUTH_SESSION_TTL_SECONDS", 28800, minimum=300, maximum=86400
    )
    if public_origin is not None:
        parsed_origin = urlsplit(public_origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.netloc
            or not parsed_origin.hostname
            or parsed_origin.path
            or parsed_origin.query
            or parsed_origin.fragment
            or parsed_origin.username
            or parsed_origin.password
        ):
            raise ValueError("APP_PUBLIC_ORIGIN must be an origin without a path")
    if auth_enabled:
        if (
            not auth_issuer_url
            or not auth_client_id
            or not auth_client_secret
            or not auth_session_signing_key
            or not auth_subject
            or not auth_scope_id
        ):
            raise ValueError(
                "OIDC authentication requires AUTH_ISSUER_URL, AUTH_CLIENT_ID, "
                "AUTH_CLIENT_SECRET, AUTH_SESSION_SIGNING_KEY, "
                "AUTH_ALLOWED_SUBJECT and AUTH_PERSONAL_SCOPE_ID"
            )
        parsed_issuer = urlsplit(auth_issuer_url)
        if (
            parsed_issuer.scheme != "https"
            or not parsed_issuer.netloc
            or not parsed_issuer.hostname
            or parsed_issuer.query
            or parsed_issuer.fragment
            or parsed_issuer.username
            or parsed_issuer.password
        ):
            raise ValueError("AUTH_ISSUER_URL must be an HTTPS issuer URL")
        if public_origin is None or not public_origin.startswith("https://"):
            raise ValueError("OIDC authentication requires an HTTPS APP_PUBLIC_ORIGIN")
        if len(auth_session_signing_key) < 32 or not auth_session_signing_key.isascii():
            raise ValueError(
                "AUTH_SESSION_SIGNING_KEY must contain at least 32 characters"
            )
        if (
            len(auth_client_id) > 512
            or len(auth_client_secret) > 4096
            or len(auth_issuer_url) > 1000
            or len(auth_subject) > 200
            or len(auth_scope_id) > 64
        ):
            raise ValueError("Authentication identity fields exceed their size limits")
    if app_env == "production":
        if not auth_enabled:
            raise ValueError("Production requires AUTH_ENABLED=true")
        if public_origin is None or not public_origin.startswith("https://"):
            raise ValueError("Production requires an HTTPS APP_PUBLIC_ORIGIN")
        if not cookie_secure:
            raise ValueError("Production authentication cookies must be Secure")
        if storage_backend != "gcs" or not private_bucket or not gcp_project:
            raise ValueError("Production requires private GCS storage and GCP_PROJECT")
        if environ.get("DEMO_MODE", "false").casefold() == "true":
            raise ValueError("Production cannot run DEMO_MODE")
        if worker_raw == "true":
            raise ValueError("Production uses a bounded Cloud Run Job, not API polling")
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
    if backend != "postgres":
        raise ValueError("DATABASE_BACKEND must be 'postgres'")

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
        5432,
        minimum=1,
        maximum=65535,
        fallback_env="POSTGRES_PORT",
    )
    pool_size = _int_setting("DATABASE_POOL_SIZE", 5, minimum=1, maximum=20)
    max_overflow = _int_setting("DATABASE_MAX_OVERFLOW", 5, minimum=0, maximum=20)
    if pool_size + max_overflow > 40:
        raise ValueError(
            "DATABASE_POOL_SIZE plus DATABASE_MAX_OVERFLOW must not exceed 40"
        )

    migration_url = environ.get("MIGRATION_DATABASE_URL") or None
    from app.db.urls import postgres_url

    for name, value in (
        ("DATABASE_URL", database_url),
        ("MIGRATION_DATABASE_URL", migration_url),
    ):
        if value:
            postgres_url(value, production=app_env == "production", setting=name)
    if app_env == "production" and database_url is None:
        raise ValueError("Production requires DATABASE_URL")

    pdf_timeout_seconds = _int_setting(
        "PDF_PARSER_TIMEOUT_SECONDS", 8, minimum=1, maximum=30
    )
    job_lease_seconds = _int_setting("JOB_LEASE_SECONDS", 30, minimum=10, maximum=900)
    if job_lease_seconds <= pdf_timeout_seconds:
        raise ValueError("JOB_LEASE_SECONDS must exceed PDF_PARSER_TIMEOUT_SECONDS")

    max_private_file_bytes = _int_setting(
        "MAX_PRIVATE_FILE_BYTES", 20_000_000, minimum=1024, maximum=100_000_000
    )
    max_import_file_bytes = _int_setting(
        "MAX_IMPORT_FILE_BYTES", 5_000_000, minimum=1024, maximum=20_000_000
    )
    if max_import_file_bytes > max_private_file_bytes:
        raise ValueError("MAX_IMPORT_FILE_BYTES cannot exceed MAX_PRIVATE_FILE_BYTES")

    return Settings(
        app_env=app_env,
        app_public_origin=public_origin,
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
        migration_database_url=migration_url,
        gcp_project=gcp_project,
        cloud_run_job=cloud_run_job,
        database_pool_size=pool_size,
        database_max_overflow=max_overflow,
        database_pool_recycle_seconds=_int_setting(
            "DATABASE_POOL_RECYCLE_SECONDS", 3000, minimum=60, maximum=3500
        ),
        database_connect_timeout_seconds=_int_setting(
            "DATABASE_CONNECT_TIMEOUT_SECONDS", 3, minimum=1, maximum=30
        ),
        private_file_dir=environ.get("PRIVATE_FILE_DIR", "./.private"),
        file_storage_backend=storage_backend,
        private_gcs_bucket=private_bucket,
        max_private_file_bytes=max_private_file_bytes,
        max_import_file_bytes=max_import_file_bytes,
        max_import_rows=_int_setting(
            "MAX_IMPORT_ROWS", 5000, minimum=1, maximum=20_000
        ),
        max_pdf_pages=_int_setting("MAX_PDF_PAGES", 40, minimum=1, maximum=100),
        pdf_parser_timeout_seconds=pdf_timeout_seconds,
        job_worker_enabled=worker_raw == "true",
        job_poll_interval_seconds=_int_setting(
            "JOB_POLL_INTERVAL_SECONDS", 1, minimum=1, maximum=30
        ),
        job_lease_seconds=job_lease_seconds,
        job_max_attempts=_int_setting("JOB_MAX_ATTEMPTS", 3, minimum=1, maximum=8),
        auth_enabled=auth_enabled,
        auth_issuer_url=auth_issuer_url,
        auth_client_id=auth_client_id,
        auth_client_secret=auth_client_secret,
        auth_session_signing_key=auth_session_signing_key,
        auth_allowed_subject=auth_subject,
        auth_personal_scope_id=auth_scope_id,
        auth_session_ttl_seconds=session_ttl,
        auth_cookie_secure=cookie_secure,
    )
