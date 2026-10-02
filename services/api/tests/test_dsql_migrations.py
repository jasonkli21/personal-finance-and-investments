"""Local structural and mocked resume checks for the DSQL migration runner."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

import pytest

from app.db import dsql_migrations
from app.db.dsql_migrations import (
    DsqlMigration,
    DsqlMigrationStep,
    MigrationPlanError,
    run_dsql_migrations,
    validate_migration_plan,
)


class FakeResult:
    def __init__(self, value: object = None) -> None:
        self.value = value

    def first(self) -> tuple[object, ...] | None:
        if self.value is None:
            return None
        return (self.value,)

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
        if "CREATE TABLE IF NOT EXISTS dsql_schema_migration_steps" in sql:
            self.engine.ledger_exists = True
            return FakeResult()
        if sql.startswith("CREATE TABLE synthetic"):
            self.engine.tables.add("synthetic")
            return FakeResult()
        if sql.startswith("CREATE INDEX ASYNC ix_synthetic"):
            self.engine.index_exists = True
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
            return FakeResult()
        raise AssertionError(f"Unexpected SQL in fake DSQL connection: {sql}")


class FakeEngine:
    def __init__(self) -> None:
        self.ledger_exists = False
        self.ledger: dict[tuple[str, str], str] = {}
        self.tables: set[str] = set()
        self.index_exists = False
        self.index_ready = False
        self.transactions: list[list[str]] = []
        self.current_transaction: list[str] = []

    def begin(self) -> FakeConnection:
        return FakeConnection(self)

    def connect(self) -> FakeConnection:
        return FakeConnection(self)


def test_core_plan_has_single_statement_steps_and_async_indexes() -> None:
    validate_migration_plan(dsql_migrations.DSQL_MIGRATIONS)
    plan = dsql_migrations.describe_migration_plan()
    assert len(plan) == 13
    assert sum(row["kind"] == "table" for row in plan) == 7
    assert sum(row["kind"] == "index" for row in plan) == 4
    assert sum(row["kind"] == "alter" for row in plan) == 2
    assert all(";" not in row["statement"] for row in plan)


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
