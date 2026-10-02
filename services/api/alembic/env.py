from logging.config import fileConfig
from os import environ

from alembic.util import CommandError
from sqlalchemy import engine_from_config, pool

from alembic import context
from app.db.models import Base

config = context.config
backend = environ.get("DATABASE_BACKEND", "postgres")
if backend != "postgres":
    raise CommandError(
        "Alembic migrations support DATABASE_BACKEND=postgres only; "
        "use `python -m app.db.migrate_dsql` for Aurora DSQL."
    )
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    explicit_url = environ.get("DATABASE_URL")
    if explicit_url:
        return explicit_url
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
