"""Explicit command entry point for applying Aurora DSQL migrations."""

from app.config import load_settings
from app.db.dsql_migrations import run_dsql_migrations
from app.db.engine import DatabaseEngineFactory


def main() -> None:
    settings = load_settings()
    if settings.database_backend != "aurora_dsql":
        raise SystemExit("Set DATABASE_BACKEND=aurora_dsql to run DSQL migrations")
    engine = DatabaseEngineFactory.create(settings, purpose="migration")
    try:
        run_dsql_migrations(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
