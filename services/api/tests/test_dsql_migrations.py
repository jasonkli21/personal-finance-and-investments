"""Local structural and mocked resume checks for the DSQL migration runner."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

import pytest
from sqlalchemy import UniqueConstraint

from app.db import dsql_migrations
from app.db.dsql_migrations import (
    DsqlMigration,
    DsqlMigrationStep,
    MigrationPlanError,
    run_dsql_migrations,
    validate_migration_plan,
)
from app.db.models import Base


class FakeResult:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def first(self) -> tuple[object, ...] | None:
        if self.value is None:
            return None
        return (self.value,)

    def all(self) -> list[tuple[object, ...]]:
        return [] if self.value is None else [(self.value,)]

    def scalar_one_or_none(self) -> object:
        return self.value

    @property
    def returns_rows(self) -> bool:
        return self.value is not None


class FakeConnection:
    def __init__(self, engine: FakeEngine) -> None:
        self.engine = engine

    def __enter__(self) -> Self:
        self.engine.current_transaction = []
        return self

    def __exit__(self, *_args: object) -> None:
        self.engine.transactions.append(self.engine.current_transaction)
        self.engine.current_transaction = []

    def execute(
        self, statement: object, parameters: Mapping[str, object] | None = None
    ) -> FakeResult:
        sql = str(statement)
        values: Mapping[str, object] = parameters or {}
        self.engine.current_transaction.append(sql)
        if "pg_catalog.pg_get_indexdef" in sql:
            if "AND i.indisvalid" in sql and not self.engine.index_ready:
                return FakeResult(None)
            return FakeResult(self.engine.index_definition)
        if "WITH expected_columns" in sql:
            return FakeResult(self.engine.table_definition_matches)
        if "FROM information_schema.columns" in sql:
            if "column_default LIKE" in sql or "column_default =" in sql:
                return FakeResult(self.engine.column_definition_matches)
            return FakeResult(self.engine.column_exists)
        if "CREATE TABLE IF NOT EXISTS dsql_schema_migration_steps" in sql:
            self.engine.ledger_exists = True
            return FakeResult()
        if sql.startswith("CREATE TABLE synthetic"):
            self.engine.tables.add("synthetic")
            return FakeResult()
        if sql.startswith("CREATE INDEX ASYNC ix_synthetic"):
            self.engine.index_exists = True
            self.engine.index_definition = (
                "CREATE INDEX ix_synthetic ON synthetic USING btree (id)"
            )
            return FakeResult("synthetic-job")
        if "CALL sys.wait_for_job" in sql:
            self.engine.index_ready = True
            return FakeResult(True)
        if sql.startswith("INSERT INTO dsql_schema_migration_steps"):
            key = (str(values["revision"]), str(values["step_key"]))
            self.engine.ledger[key] = str(values["checksum"])
            return FakeResult()
        if "SELECT checksum FROM dsql_schema_migration_steps" in sql:
            key = (str(values["revision"]), str(values["step_key"]))
            return FakeResult(self.engine.ledger.get(key))
        if "FROM information_schema.tables" in sql:
            return FakeResult(str(values["object_name"]) in self.engine.tables)
        if "FROM pg_catalog.pg_index" in sql:
            return FakeResult(self.engine.index_ready)
        if "FROM pg_catalog.pg_class" in sql:
            return FakeResult(self.engine.index_exists)
        if "FROM sys.jobs" in sql:
            return FakeResult(None)
        if sql.startswith("DROP INDEX IF EXISTS"):
            self.engine.index_exists = False
            self.engine.index_ready = False
            self.engine.index_definition = None
            return FakeResult()
        raise AssertionError(f"Unexpected SQL in fake DSQL connection: {sql}")


class FakeEngine:
    def __init__(self) -> None:
        self.ledger_exists = False
        self.ledger: dict[tuple[str, str], str] = {}
        self.tables: set[str] = set()
        self.index_exists = False
        self.index_ready = False
        self.index_definition: str | None = None
        self.table_definition_matches = False
        self.column_exists = False
        self.column_definition_matches = False
        self.transactions: list[list[str]] = []
        self.current_transaction: list[str] = []

    def begin(self) -> FakeConnection:
        return FakeConnection(self)

    def connect(self) -> FakeConnection:
        return FakeConnection(self)


def test_core_plan_has_single_statement_steps_and_async_indexes() -> None:
    validate_migration_plan(dsql_migrations.DSQL_MIGRATIONS)
    plan = dsql_migrations.describe_migration_plan()
    assert len(plan) == 95
    assert sum(row["kind"] == "table" for row in plan) == 45
    assert sum(row["kind"] == "index" for row in plan) == 37
    assert sum(row["kind"] == "alter" for row in plan) == 6
    assert sum(row["kind"] == "backfill" for row in plan) == 1
    assert all(";" not in row["statement"] for row in plan)


def test_named_unique_constraints_do_not_collide_between_tables() -> None:
    constraint_tables: dict[str, str] = {}
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            name = constraint.name
            if not isinstance(constraint, UniqueConstraint) or not isinstance(
                name, str
            ):
                continue
            previous_table = constraint_tables.setdefault(name, table.name)
            assert previous_table == table.name, (
                f"Unique constraint name {name!r} is shared by "
                f"{previous_table!r} and {table.name!r}."
            )


def test_migration_plan_rejects_multiple_statements() -> None:
    invalid = DsqlMigration(
        "0001_invalid",
        (
            DsqlMigrationStep(
                "bad",
                "table",
                "CREATE TABLE first (id uuid); CREATE TABLE second (id uuid)",
                "first",
                "SELECT false",
            ),
        ),
    )
    with pytest.raises(MigrationPlanError, match="multiple SQL statements"):
        validate_migration_plan((invalid,))


def test_runner_resumes_after_ddl_commits_before_ledger_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = FakeEngine()
    migration = DsqlMigration(
        "0001_synthetic",
        (
            DsqlMigrationStep(
                "create_table",
                "table",
                "CREATE TABLE synthetic (id uuid)",
                "synthetic",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "create_index",
                "index",
                "CREATE INDEX ASYNC ix_synthetic ON synthetic (id)",
                "ix_synthetic",
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_index WHERE indisvalid "
                "AND index_name = :object_name)",
                expected_index_table="synthetic",
                expected_index_columns=("id",),
            ),
        ),
    )
    record_complete = dsql_migrations._record_complete
    fail_once = True

    def interrupted(*args: Any, **kwargs: Any) -> None:
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("synthetic process interruption")
        record_complete(*args, **kwargs)

    monkeypatch.setattr(dsql_migrations, "_record_complete", interrupted)
    with pytest.raises(RuntimeError, match="process interruption"):
        run_dsql_migrations(engine, (migration,))  # type: ignore[arg-type]
    create_count_before_resume = sum(
        statement.startswith("CREATE TABLE synthetic")
        for transaction in engine.transactions
        for statement in transaction
    )
    assert create_count_before_resume == 1

    run_dsql_migrations(engine, (migration,))  # type: ignore[arg-type]

    create_count_after_resume = sum(
        statement.startswith("CREATE TABLE synthetic")
        for transaction in engine.transactions
        for statement in transaction
    )
    assert create_count_after_resume == 1
    ddl_transactions = [
        transaction
        for transaction in engine.transactions
        if any(statement.startswith("CREATE ") for statement in transaction)
    ]
    assert all(len(transaction) == 1 for transaction in ddl_transactions)


def test_unrecorded_table_with_incompatible_definition_is_not_adopted() -> None:
    engine = FakeEngine()
    engine.tables.add("issuers")
    migration = DsqlMigration(
        "0001_core_portfolio_schema",
        (dsql_migrations.CORE_SCHEMA.steps[0],),
    )
    with pytest.raises(MigrationPlanError, match="table definition drift"):
        run_dsql_migrations(engine, (migration,))  # type: ignore[arg-type]
    assert not any(
        statement.startswith("CREATE TABLE issuers")
        for transaction in engine.transactions
        for statement in transaction
    )


def test_unrecorded_index_with_incompatible_key_is_rejected_without_drop() -> None:
    engine = FakeEngine()
    engine.index_exists = True
    engine.index_ready = True
    engine.index_definition = "CREATE INDEX ix_synthetic ON other USING btree (id)"
    step = DsqlMigrationStep(
        "create_index",
        "index",
        "CREATE INDEX ASYNC ix_synthetic ON synthetic (id)",
        "ix_synthetic",
        "SELECT true",
        expected_index_table="synthetic",
        expected_index_columns=("id",),
    )
    with pytest.raises(MigrationPlanError, match="index definition drift"):
        run_dsql_migrations(engine, (DsqlMigration("0001_synthetic", (step,)),))  # type: ignore[arg-type]
    assert engine.index_exists
    assert not any(
        statement.startswith("DROP INDEX")
        for transaction in engine.transactions
        for statement in transaction
    )


def test_completed_constraint_validation_keeps_earlier_add_step_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = next(
        step
        for step in dsql_migrations.IMMUTABLE_POSITION_REVISIONS_AND_IDENTIFIERS.steps
        if step.key == "add_current_snapshot_foreign_key"
    )
    monkeypatch.setattr(dsql_migrations, "_constraint_exists", lambda *_args: True)
    monkeypatch.setattr(
        dsql_migrations,
        "_constraint_matches",
        lambda _engine, _expected, *, validated: validated in {None, True},
    )

    assert dsql_migrations._is_complete(FakeEngine(), step)  # type: ignore[arg-type]


def test_legacy_ledger_checksums_remain_compatible() -> None:
    # Frozen hashes recorded by the original 0001/0002 runner.
    expected = {
        "create_issuers": (
            "453d00e08c7d4b5c115befe1eeeaee58e31a2bc0ac4d965c4092b2f07c297291"
        ),
        "create_accounts": (
            "a07db243be492d932027f41a9030054c758bff305adf0aa72b80093821bec70b"
        ),
        "create_issuer_aliases": (
            "544cef6796c8e7a19b6155799b2c15a60702596a2a857ec98c1d076ec5d41267"
        ),
        "create_securities": (
            "cb93609d4a8787f44bdac68959c85800d0da7a87a6500ca7f603e34eb71383a8"
        ),
        "create_position_snapshots": (
            "6a9dbea9ca96430e9e8aea31dd6f3c042f4716a08583862a4bf08f8e1c5bc57a"
        ),
        "create_quotes": (
            "dd196ff5355e16c18304b06ab4d425ba7a35a6a4afaaa601ecef1f925dd6341d"
        ),
        "create_position_snapshot_lines": (
            "6252202525a7f7239ee75f305dd5d72039ac72b9d9c0e375f5d09b97fb082a2f"
        ),
        "create_index_ix_issuer_aliases_normalized_alias": (
            "abe7a892b1e61970df3ba657d5c9e7d33d40583774a3564cf13982f7a79effca"
        ),
        "create_index_ix_position_snapshots_account_asof": (
            "6276cf1a9bae84e76c16d34881b826b92cf250da694a2614be3da25d0cda5406"
        ),
        "create_index_ix_quotes_security_asof": (
            "802bb0fb5ad98b4ee68e31bc2625a4444562aab3bad4b11d2004a1a2832c4d82"
        ),
        "create_index_ix_position_lines_snapshot": (
            "f7e3b24895887e1f63f61c20a3772413126a15c8bf60b76036690eece241cc3e"
        ),
        "add_account_current_position_revision": (
            "e74b63765860df6a54acafc30d377d31dc874576a75cee9ca8250069b116b969"
        ),
        "add_position_snapshot_revision": (
            "a36c8733ab1494993e4ddad00f342749ba8f4b1922314ba5377c7e96cd50536b"
        ),
    }
    actual = {
        step.key: step.checksum
        for migration in (
            dsql_migrations.CORE_SCHEMA,
            dsql_migrations.POSITION_SNAPSHOT_REVISION,
        )
        for step in migration.steps
    }
    assert actual == expected


def test_legacy_ledger_resumes_and_still_rejects_statement_drift() -> None:
    from dataclasses import replace

    step = dsql_migrations.CORE_SCHEMA.steps[0]
    engine = FakeEngine()
    engine.tables.add("issuers")
    engine.table_definition_matches = True
    revision = "0001_core_portfolio_schema"
    engine.ledger[(revision, step.key)] = (
        "453d00e08c7d4b5c115befe1eeeaee58e31a2bc0ac4d965c4092b2f07c297291"
    )
    run_dsql_migrations(engine, (DsqlMigration(revision, (step,)),))  # type: ignore[arg-type]
    changed = replace(step, statement=step.statement + " ")
    with pytest.raises(MigrationPlanError, match="Applied DSQL migration drift"):
        run_dsql_migrations(engine, (DsqlMigration(revision, (changed,)),))  # type: ignore[arg-type]
    engine.table_definition_matches = False
    with pytest.raises(MigrationPlanError, match="table definition drift"):
        run_dsql_migrations(engine, (DsqlMigration(revision, (step,)),))  # type: ignore[arg-type]


def test_schema_evolution_does_not_change_prior_checksums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    step = dsql_migrations.CORE_SCHEMA.steps[0]
    checksum = step.checksum
    monkeypatch.setitem(
        dsql_migrations.TABLE_EVOLUTIONS, "issuers", ((), (), frozenset())
    )
    monkeypatch.setitem(dsql_migrations.TABLE_COLUMNS, "issuers", ())
    assert step.checksum == checksum
