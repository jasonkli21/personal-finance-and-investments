"""Versioned Aurora DSQL DDL plan and resumable migration runner.

Each DDL step commits in its own transaction. The migration ledger is created
in a separate DDL transaction and updated with standalone DML transactions.
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from sqlalchemy import Engine, text

StepKind = Literal["table", "index", "alter"]


@dataclass(frozen=True)
class DsqlMigrationStep:
    key: str
    kind: StepKind
    statement: str
    object_name: str
    ready_check: str

    @property
    def checksum(self) -> str:
        material = "\0".join(
            (self.key, self.kind, self.statement, self.object_name, self.ready_check)
        )
        return sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class DsqlMigration:
    revision: str
    steps: tuple[DsqlMigrationStep, ...]


CORE_SCHEMA = DsqlMigration(
    revision="0001_core_portfolio_schema",
    steps=(
        DsqlMigrationStep(
            "create_issuers",
            "table",
            """CREATE TABLE issuers (
                id uuid NOT NULL,
                normalized_name varchar(200) NOT NULL,
                display_name varchar(200) NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT issuers_pkey PRIMARY KEY (id),
                CONSTRAINT issuers_normalized_name_key UNIQUE (normalized_name)
            )""",
            "issuers",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        DsqlMigrationStep(
            "create_accounts",
            "table",
            """CREATE TABLE accounts (
                id uuid NOT NULL,
                name varchar(200) NOT NULL,
                account_type varchar(40) NOT NULL,
                base_currency varchar(3) NOT NULL,
                active boolean NOT NULL,
                source_type varchar(40) NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT accounts_pkey PRIMARY KEY (id)
            )""",
            "accounts",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        DsqlMigrationStep(
            "create_issuer_aliases",
            "table",
            """CREATE TABLE issuer_aliases (
                id uuid NOT NULL,
                issuer_id uuid NOT NULL,
                alias varchar(200) NOT NULL,
                normalized_alias varchar(200) NOT NULL,
                source varchar(100) NOT NULL,
                CONSTRAINT issuer_aliases_pkey PRIMARY KEY (id),
                CONSTRAINT fk_issuer_aliases_issuer FOREIGN KEY (issuer_id)
                    REFERENCES issuers (id) ON DELETE CASCADE,
                CONSTRAINT uq_issuer_alias UNIQUE (issuer_id, normalized_alias)
            )""",
            "issuer_aliases",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        DsqlMigrationStep(
            "create_securities",
            "table",
            """CREATE TABLE securities (
                id uuid NOT NULL,
                security_type varchar(20) NOT NULL,
                display_ticker varchar(32),
                name varchar(200) NOT NULL,
                issuer_id uuid,
                currency varchar(3) NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT securities_pkey PRIMARY KEY (id),
                CONSTRAINT ck_securities_security_type
                    CHECK (security_type IN ('equity', 'etf', 'cash', 'other')),
                CONSTRAINT fk_securities_issuer FOREIGN KEY (issuer_id)
                    REFERENCES issuers (id) ON DELETE SET NULL
            )""",
            "securities",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        DsqlMigrationStep(
            "create_position_snapshots",
            "table",
            """CREATE TABLE position_snapshots (
                id uuid NOT NULL,
                account_id uuid NOT NULL,
                snapshot_at timestamptz NOT NULL,
                source varchar(100) NOT NULL,
                valuation_source varchar(100),
                status varchar(24) NOT NULL,
                accepted_at timestamptz,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT position_snapshots_pkey PRIMARY KEY (id),
                CONSTRAINT uq_position_snapshot_identity
                    UNIQUE (account_id, snapshot_at, source),
                CONSTRAINT fk_position_snapshots_account FOREIGN KEY (account_id)
                    REFERENCES accounts (id) ON DELETE RESTRICT
            )""",
            "position_snapshots",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        DsqlMigrationStep(
            "create_quotes",
            "table",
            """CREATE TABLE quotes (
                id uuid NOT NULL,
                security_id uuid NOT NULL,
                as_of timestamptz NOT NULL,
                price numeric(24, 10) NOT NULL,
                currency varchar(3) NOT NULL,
                source varchar(100) NOT NULL,
                fetched_at timestamptz NOT NULL,
                quality_status varchar(24) NOT NULL,
                provider_metadata jsonb NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT quotes_pkey PRIMARY KEY (id),
                CONSTRAINT ck_quotes_price_nonnegative CHECK (price >= 0),
                CONSTRAINT uq_quotes_security_asof_source
                    UNIQUE (security_id, as_of, source),
                CONSTRAINT fk_quotes_security FOREIGN KEY (security_id)
                    REFERENCES securities (id) ON DELETE RESTRICT
            )""",
            "quotes",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        DsqlMigrationStep(
            "create_position_snapshot_lines",
            "table",
            """CREATE TABLE position_snapshot_lines (
                id uuid NOT NULL,
                snapshot_id uuid NOT NULL,
                security_id uuid,
                unresolved_ref text,
                quantity numeric(28, 10) NOT NULL,
                reported_value numeric(28, 10),
                reported_price numeric(24, 10),
                currency varchar(3) NOT NULL,
                original_row_ref varchar(200),
                source varchar(100) NOT NULL,
                quality_status varchar(24) NOT NULL,
                CONSTRAINT position_snapshot_lines_pkey PRIMARY KEY (id),
                CONSTRAINT ck_position_line_security_or_unresolved CHECK (
                    (security_id IS NOT NULL AND unresolved_ref IS NULL) OR
                    (security_id IS NULL AND unresolved_ref IS NOT NULL)
                ),
                CONSTRAINT fk_position_lines_security FOREIGN KEY (security_id)
                    REFERENCES securities (id) ON DELETE RESTRICT,
                CONSTRAINT fk_position_lines_snapshot FOREIGN KEY (snapshot_id)
                    REFERENCES position_snapshots (id) ON DELETE CASCADE
            )""",
            "position_snapshot_lines",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = :object_name
            )""",
        ),
        *(
            DsqlMigrationStep(
                f"create_index_{name}",
                "index",
                statement,
                name,
                """SELECT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_index i
                    JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = current_schema()
                      AND c.relname = :object_name
                      AND i.indisvalid
                )""",
            )
            for name, statement in (
                (
                    "ix_issuer_aliases_normalized_alias",
                    "CREATE INDEX ASYNC ix_issuer_aliases_normalized_alias "
                    "ON issuer_aliases (normalized_alias)",
                ),
                (
                    "ix_position_snapshots_account_asof",
                    "CREATE INDEX ASYNC ix_position_snapshots_account_asof "
                    "ON position_snapshots (account_id, snapshot_at)",
                ),
                (
                    "ix_quotes_security_asof",
                    "CREATE INDEX ASYNC ix_quotes_security_asof "
                    "ON quotes (security_id, as_of)",
                ),
                (
                    "ix_position_lines_snapshot",
                    "CREATE INDEX ASYNC ix_position_lines_snapshot "
                    "ON position_snapshot_lines (snapshot_id)",
                ),
            )
        ),
    ),
)

POSITION_SNAPSHOT_REVISION = DsqlMigration(
    revision="0002_position_snapshot_revision",
    steps=(
        DsqlMigrationStep(
            "add_account_current_position_revision",
            "alter",
            "ALTER TABLE accounts ADD COLUMN current_position_revision integer "
            "NOT NULL DEFAULT 0",
            "accounts.current_position_revision",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'accounts'
                  AND column_name = 'current_position_revision'
            )""",
        ),
        DsqlMigrationStep(
            "add_position_snapshot_revision",
            "alter",
            "ALTER TABLE position_snapshots ADD COLUMN revision integer "
            "NOT NULL DEFAULT 1",
            "position_snapshots.revision",
            """SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'position_snapshots'
                  AND column_name = 'revision'
            )""",
        ),
    ),
)

DSQL_MIGRATIONS = (CORE_SCHEMA, POSITION_SNAPSHOT_REVISION)
LEDGER_DDL = """CREATE TABLE IF NOT EXISTS dsql_schema_migration_steps (
    revision varchar(128) NOT NULL,
    step_key varchar(128) NOT NULL,
    checksum varchar(64) NOT NULL,
    completed_at timestamptz NOT NULL,
    CONSTRAINT dsql_schema_migration_steps_pkey PRIMARY KEY (revision, step_key)
)"""


class MigrationPlanError(RuntimeError):
    """The local DSQL plan is malformed or has drifted from the ledger."""


def validate_migration_plan(migrations: tuple[DsqlMigration, ...]) -> None:
    seen_revisions: set[str] = set()
    for migration in migrations:
        if not migration.revision or migration.revision in seen_revisions:
            raise MigrationPlanError(
                "DSQL migration revisions must be unique and named"
            )
        seen_revisions.add(migration.revision)
        seen_keys: set[str] = set()
        for step in migration.steps:
            if not step.key or step.key in seen_keys:
                raise MigrationPlanError(
                    f"Step keys must be unique in {migration.revision}"
                )
            seen_keys.add(step.key)
            if ";" in step.statement:
                raise MigrationPlanError(
                    f"{migration.revision}/{step.key} contains multiple SQL statements"
                )
            if step.kind == "table" and not step.statement.lstrip().upper().startswith(
                "CREATE TABLE"
            ):
                raise MigrationPlanError(f"{step.key} is not a CREATE TABLE step")
            if step.kind == "index" and not step.statement.lstrip().upper().startswith(
                "CREATE INDEX ASYNC"
            ):
                raise MigrationPlanError(
                    f"{step.key} is not an asynchronous index step"
                )
            if step.kind == "alter" and not step.statement.lstrip().upper().startswith(
                "ALTER TABLE"
            ):
                raise MigrationPlanError(f"{step.key} is not an ALTER TABLE step")
            if not step.ready_check:
                raise MigrationPlanError(f"{step.key} has no completion check")


def _scalar(engine: Engine, statement: str, **parameters: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(statement), parameters).scalar_one_or_none()


def _execute_one(engine: Engine, statement: str, **parameters: object) -> object:
    with engine.begin() as connection:
        result = connection.execute(text(statement), parameters)
        if not result.returns_rows:
            return None
        row = result.first()
        return row[0] if row is not None else None


def _record_complete(engine: Engine, revision: str, step: DsqlMigrationStep) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO dsql_schema_migration_steps "
                "(revision, step_key, checksum, completed_at) "
                "VALUES (:revision, :step_key, :checksum, CURRENT_TIMESTAMP) "
                "ON CONFLICT (revision, step_key) DO NOTHING"
            ),
            {
                "revision": revision,
                "step_key": step.key,
                "checksum": step.checksum,
            },
        )


def _wait_for_index(engine: Engine, job_id: object) -> None:
    with engine.begin() as connection:
        result = connection.execute(
            text("CALL sys.wait_for_job(:job_id)"), {"job_id": job_id}
        )
        row = result.first()
        if row is not None and row[0] is False:
            raise RuntimeError(f"Aurora DSQL index job {job_id} failed")


def _index_exists(engine: Engine, name: str) -> bool:
    result = _scalar(
        engine,
        """SELECT EXISTS (
            SELECT 1 FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relname = :object_name
        )""",
        object_name=name,
    )
    return bool(result)


def _resume_index(engine: Engine, step: DsqlMigrationStep) -> bool:
    ready = bool(_scalar(engine, step.ready_check, object_name=step.object_name))
    if ready:
        return True
    if not _index_exists(engine, step.object_name):
        return False
    pending = _scalar(
        engine,
        """SELECT job_id FROM sys.jobs
            WHERE object_name = :qualified_name
              AND job_type = 'INDEX_BUILD'
              AND status NOT IN ('completed', 'failed')
            ORDER BY start_time DESC LIMIT 1""",
        qualified_name=f"public.{step.object_name}",
    )
    if pending is not None:
        _wait_for_index(engine, pending)
        if bool(_scalar(engine, step.ready_check, object_name=step.object_name)):
            return True
    # DSQL leaves a failed async index INVALID. Remove this plan-owned index
    # in its own DDL transaction so a later execution can safely recreate it.
    _execute_one(engine, f"DROP INDEX IF EXISTS {step.object_name}")
    return False


def _is_complete(engine: Engine, step: DsqlMigrationStep) -> bool:
    if step.kind == "index":
        return _resume_index(engine, step)
    return bool(_scalar(engine, step.ready_check, object_name=step.object_name))


def run_dsql_migrations(
    engine: Engine,
    migrations: tuple[DsqlMigration, ...] = DSQL_MIGRATIONS,
) -> None:
    """Apply or resume the versioned core DSQL migration plan."""
    validate_migration_plan(migrations)
    # Ledger bootstrap is exactly one DDL statement in its own transaction.
    with engine.begin() as connection:
        connection.execute(text(LEDGER_DDL))

    for migration in migrations:
        for step in migration.steps:
            saved_checksum = _scalar(
                engine,
                "SELECT checksum FROM dsql_schema_migration_steps "
                "WHERE revision = :revision AND step_key = :step_key",
                revision=migration.revision,
                step_key=step.key,
            )
            if saved_checksum is not None:
                if saved_checksum != step.checksum:
                    raise MigrationPlanError(
                        "Applied DSQL migration drift at "
                        f"{migration.revision}/{step.key}"
                    )
                continue

            if not _is_complete(engine, step):
                result = _execute_one(engine, step.statement)
                if step.kind == "index":
                    if result is None:
                        raise RuntimeError(
                            f"Aurora DSQL did not return an index job id for {step.key}"
                        )
                    _wait_for_index(engine, result)
                if not _is_complete(engine, step):
                    raise RuntimeError(
                        f"Aurora DSQL did not complete {migration.revision}/{step.key}"
                    )

            # Ledger DML is a new transaction, after the DDL / index wait.
            _record_complete(engine, migration.revision, step)


def describe_migration_plan(
    migrations: tuple[DsqlMigration, ...] = DSQL_MIGRATIONS,
) -> list[dict[str, str]]:
    validate_migration_plan(migrations)
    return [
        {
            "revision": migration.revision,
            "step": step.key,
            "kind": step.kind,
            "statement": step.statement,
            "checksum": step.checksum,
        }
        for migration in migrations
        for step in migration.steps
    ]
