from logging.config import fileConfig
from os import environ

from sqlalchemy import engine_from_config, inspect, pool

from alembic import context
from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_ALEMBIC_VERSION_LENGTH = 128


def database_url() -> str:
    explicit_url = environ.get("MIGRATION_DATABASE_URL") or environ.get("DATABASE_URL")
    if explicit_url:
        from app.db.urls import postgres_url

        return postgres_url(
            explicit_url,
            production=environ.get("APP_ENV", "development").casefold() == "production",
            setting="migration connection",
        ).render_as_string(hide_password=False)
    if environ.get("APP_ENV", "development").casefold() == "production":
        raise ValueError(
            "Production migrations require DATABASE_URL or MIGRATION_DATABASE_URL"
        )
    host = environ.get("DATABASE_HOST", "127.0.0.1")
    port = environ.get("DATABASE_PORT", environ.get("POSTGRES_PORT", "5432"))
    user = environ.get("DATABASE_USER", environ.get("POSTGRES_USER", "portfolio"))
    password = environ.get(
        "DATABASE_PASSWORD", environ.get("POSTGRES_PASSWORD", "local-only-change-me")
    )
    name = environ.get("DATABASE_NAME", environ.get("POSTGRES_DB", "portfolio"))
    from sqlalchemy.engine import URL

    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=int(port),
        database=name,
    ).render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    # Alembic's default version table uses VARCHAR(32), which is too short for
    # the descriptive revision identifiers in this repository. Create or widen
    # the PostgreSQL bookkeeping table before Alembic applies any migrations.
    with connectable.begin() as connection:
        inspector = inspect(connection)
        if inspector.has_table("alembic_version"):
            version_column = next(
                column
                for column in inspector.get_columns("alembic_version")
                if column["name"] == "version_num"
            )
            current_length = getattr(version_column["type"], "length", None)
            if current_length is not None and current_length < _ALEMBIC_VERSION_LENGTH:
                connection.exec_driver_sql(
                    "ALTER TABLE alembic_version "
                    f"ALTER COLUMN version_num TYPE VARCHAR({_ALEMBIC_VERSION_LENGTH})"
                )
        else:
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version ("
                f"version_num VARCHAR({_ALEMBIC_VERSION_LENGTH}) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
