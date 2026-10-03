"""Versioned Aurora DSQL DDL plan and resumable migration runner.

Each DDL step commits in its own transaction. The migration ledger is created
in a separate DDL transaction and updated with standalone DML transactions.
"""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from sqlalchemy import Engine, text

StepKind = Literal[
    "table",
    "index",
    "alter",
    "backfill",
    "drop_constraint",
    "add_constraint",
    "async_alter",
]

ColumnSignature = tuple[str, str, str, int | None, int | None, int | None]
ConstraintSignature = tuple[str, str, tuple[str, ...]]


@dataclass(frozen=True)
class DsqlMigrationStep:
    key: str
    kind: StepKind
    statement: str
    object_name: str
    ready_check: str
    expected_index_table: str | None = None
    expected_index_columns: tuple[str, ...] = ()
    expected_index_unique: bool = False
    expected_column: tuple[str, str, str | None] | None = None
    expected_constraint: tuple[str, str, str, tuple[str, ...]] | None = None
    expected_constraint_validated: bool | None = None

    @property
    def checksum(self) -> str:
        # Ledger identity is the immutable executable step, not the evolving
        # schema validators. Keep the original algorithm for existing ledgers.
        material = "\0".join(
            (self.key, self.kind, self.statement, self.object_name, self.ready_check)
        )
        return sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class DsqlMigration:
    revision: str
    steps: tuple[DsqlMigrationStep, ...]


TABLE_COLUMNS: dict[str, tuple[ColumnSignature, ...]] = {
    "issuers": (
        ("id", "uuid", "NO", None, None, None),
        ("normalized_name", "character varying", "NO", 200, None, None),
        ("display_name", "character varying", "NO", 200, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "accounts": (
        ("id", "uuid", "NO", None, None, None),
        ("name", "character varying", "NO", 200, None, None),
        ("account_type", "character varying", "NO", 40, None, None),
        ("base_currency", "character varying", "NO", 3, None, None),
        ("active", "boolean", "NO", None, None, None),
        ("source_type", "character varying", "NO", 40, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "issuer_aliases": (
        ("id", "uuid", "NO", None, None, None),
        ("issuer_id", "uuid", "NO", None, None, None),
        ("alias", "character varying", "NO", 200, None, None),
        ("normalized_alias", "character varying", "NO", 200, None, None),
        ("source", "character varying", "NO", 100, None, None),
    ),
    "securities": (
        ("id", "uuid", "NO", None, None, None),
        ("security_type", "character varying", "NO", 20, None, None),
        ("display_ticker", "character varying", "YES", 32, None, None),
        ("name", "character varying", "NO", 200, None, None),
        ("issuer_id", "uuid", "YES", None, None, None),
        ("currency", "character varying", "NO", 3, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "position_snapshots": (
        ("id", "uuid", "NO", None, None, None),
        ("account_id", "uuid", "NO", None, None, None),
        ("snapshot_at", "timestamp with time zone", "NO", None, None, None),
        ("source", "character varying", "NO", 100, None, None),
        ("valuation_source", "character varying", "YES", 100, None, None),
        ("status", "character varying", "NO", 24, None, None),
        ("accepted_at", "timestamp with time zone", "YES", None, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "quotes": (
        ("id", "uuid", "NO", None, None, None),
        ("security_id", "uuid", "NO", None, None, None),
        ("as_of", "timestamp with time zone", "NO", None, None, None),
        ("price", "numeric", "NO", None, 24, 10),
        ("currency", "character varying", "NO", 3, None, None),
        ("source", "character varying", "NO", 100, None, None),
        ("fetched_at", "timestamp with time zone", "NO", None, None, None),
        ("quality_status", "character varying", "NO", 24, None, None),
        ("provider_metadata", "jsonb", "NO", None, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "position_snapshot_lines": (
        ("id", "uuid", "NO", None, None, None),
        ("snapshot_id", "uuid", "NO", None, None, None),
        ("security_id", "uuid", "YES", None, None, None),
        ("unresolved_ref", "text", "YES", None, None, None),
        ("quantity", "numeric", "NO", None, 28, 10),
        ("reported_value", "numeric", "YES", None, 28, 10),
        ("reported_price", "numeric", "YES", None, 24, 10),
        ("currency", "character varying", "NO", 3, None, None),
        ("original_row_ref", "character varying", "YES", 200, None, None),
        ("source", "character varying", "NO", 100, None, None),
        ("quality_status", "character varying", "NO", 24, None, None),
    ),
    "security_identifiers": (
        ("id", "uuid", "NO", None, None, None),
        ("security_id", "uuid", "NO", None, None, None),
        ("namespace", "character varying", "NO", 40, None, None),
        ("exchange", "character varying", "NO", 40, None, None),
        ("value", "character varying", "NO", 128, None, None),
        ("normalized_value", "character varying", "NO", 128, None, None),
        ("valid_from", "date", "NO", None, None, None),
        ("valid_to", "date", "YES", None, None, None),
        ("source", "character varying", "NO", 100, None, None),
        ("review_status", "character varying", "NO", 24, None, None),
    ),
    "private_files": (
        ("id", "uuid", "NO", None, None, None),
        ("content_hash", "character varying", "NO", 64, None, None),
        ("storage_key", "character varying", "NO", 100, None, None),
        ("original_name", "character varying", "NO", 200, None, None),
        ("content_type", "character varying", "NO", 100, None, None),
        ("byte_size", "integer", "NO", None, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "imports": (
        ("id", "uuid", "NO", None, None, None),
        ("file_id", "uuid", "NO", None, None, None),
        ("kind", "character varying", "NO", 20, None, None),
        ("account_id", "uuid", "YES", None, None, None),
        ("fund_security_id", "uuid", "YES", None, None, None),
        ("effective_date", "date", "NO", None, None, None),
        ("source_label", "character varying", "NO", 100, None, None),
        ("parser_version", "character varying", "NO", 80, None, None),
        ("column_mapping", "jsonb", "NO", None, None, None),
        ("file_sha256", "character varying", "NO", 64, None, None),
        ("identity_hash", "character varying", "NO", 64, None, None),
        ("interpretation_hash", "character varying", "NO", 64, None, None),
        ("payload_hash", "character varying", "YES", 64, None, None),
        ("status", "character varying", "NO", 24, None, None),
        ("review_revision", "integer", "NO", None, None, None),
        ("expected_account_revision", "integer", "YES", None, None, None),
        ("idempotency_key", "character varying", "NO", 128, None, None),
        ("row_count", "integer", "NO", None, None, None),
        ("batch_count", "integer", "NO", None, None, None),
        ("duplicate_of_import_id", "uuid", "YES", None, None, None),
        ("staging_snapshot_id", "uuid", "YES", None, None, None),
        ("published_snapshot_id", "uuid", "YES", None, None, None),
        ("diagnostics", "jsonb", "NO", None, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "import_batches": (
        ("id", "uuid", "NO", None, None, None),
        ("import_id", "uuid", "NO", None, None, None),
        ("purpose", "character varying", "NO", 32, None, None),
        ("review_revision", "integer", "NO", None, None, None),
        ("ordinal", "integer", "NO", None, None, None),
        ("payload_hash", "character varying", "NO", 64, None, None),
        ("row_count", "integer", "NO", None, None, None),
        ("status", "character varying", "NO", 24, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "import_rows": (
        ("id", "uuid", "NO", None, None, None),
        ("import_id", "uuid", "NO", None, None, None),
        ("row_number", "integer", "NO", None, None, None),
        ("raw_payload", "jsonb", "NO", None, None, None),
        ("raw_identifier", "character varying", "YES", 2000, None, None),
        ("raw_name", "character varying", "YES", 2000, None, None),
        ("raw_asset_type", "character varying", "YES", 2000, None, None),
        ("raw_quantity", "character varying", "YES", 2000, None, None),
        ("raw_price", "character varying", "YES", 2000, None, None),
        ("raw_currency", "character varying", "YES", 200, None, None),
        ("raw_weight_value", "character varying", "YES", 100, None, None),
        ("raw_weight_unit", "character varying", "YES", 24, None, None),
        ("security_id", "uuid", "YES", None, None, None),
        ("normalized_quantity", "numeric", "YES", None, 28, 10),
        ("normalized_price", "numeric", "YES", None, 24, 10),
        ("normalized_weight", "numeric", "YES", None, 18, 10),
        ("currency", "character varying", "YES", 3, None, None),
        ("row_status", "character varying", "NO", 24, None, None),
        ("excluded", "boolean", "NO", None, None, None),
        ("correction_reason", "text", "YES", None, None, None),
        ("diagnostics", "jsonb", "NO", None, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
        ("updated_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "import_review_events": (
        ("id", "uuid", "NO", None, None, None),
        ("import_id", "uuid", "NO", None, None, None),
        ("review_revision", "integer", "NO", None, None, None),
        ("action", "character varying", "NO", 32, None, None),
        ("reason", "character varying", "NO", 500, None, None),
        ("change_payload", "jsonb", "NO", None, None, None),
        ("created_at", "timestamp with time zone", "NO", None, None, None),
    ),
    "security_issuer_mapping_events": (
        ("id", "uuid", "NO", None, None, None),
        ("security_id", "uuid", "NO", None, None, None),
        ("previous_issuer_id", "uuid", "YES", None, None, None),
        ("new_issuer_id", "uuid", "YES", None, None, None),
        ("reason", "character varying", "NO", 500, None, None),
        ("changed_at", "timestamp with time zone", "NO", None, None, None),
    ),
}


TABLE_CONSTRAINTS: dict[str, tuple[ConstraintSignature, ...]] = {
    "issuers": (
        ("issuers_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        ("issuers_normalized_name_key", "UNIQUE", ("unique(normalized_name)",)),
    ),
    "accounts": (("accounts_pkey", "PRIMARY KEY", ("primarykey(id)",)),),
    "issuer_aliases": (
        ("issuer_aliases_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "fk_issuer_aliases_issuer",
            "FOREIGN KEY",
            ("foreignkey(issuer_id)referencesissuers(id)ondeletecascade",),
        ),
        ("uq_issuer_alias", "UNIQUE", ("unique(issuer_id,normalized_alias)",)),
    ),
    "securities": (
        ("securities_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "ck_securities_security_type",
            "CHECK",
            ("security_type", "equity", "etf", "cash", "other"),
        ),
        (
            "fk_securities_issuer",
            "FOREIGN KEY",
            ("foreignkey(issuer_id)referencesissuers(id)ondelete set null",),
        ),
    ),
    "position_snapshots": (
        ("position_snapshots_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "uq_position_snapshot_identity",
            "UNIQUE",
            ("unique(account_id,snapshot_at,source)",),
        ),
        (
            "fk_position_snapshots_account",
            "FOREIGN KEY",
            ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
        ),
    ),
    "quotes": (
        ("quotes_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        ("ck_quotes_price_nonnegative", "CHECK", ("price", ">=", "0")),
        (
            "uq_quotes_security_asof_source",
            "UNIQUE",
            ("unique(security_id,as_of,source)",),
        ),
        (
            "fk_quotes_security",
            "FOREIGN KEY",
            ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
        ),
    ),
    "position_snapshot_lines": (
        ("position_snapshot_lines_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "ck_position_line_security_or_unresolved",
            "CHECK",
            ("security_id", "unresolved_ref", "isnotnull", "isnull", "and", "or"),
        ),
        (
            "fk_position_lines_security",
            "FOREIGN KEY",
            ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
        ),
        (
            "fk_position_lines_snapshot",
            "FOREIGN KEY",
            (
                "foreignkey(snapshot_id)referencesposition_snapshots(id)"
                "ondelete cascade",
            ),
        ),
    ),
    "security_identifiers": (
        ("security_identifiers_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        ("ck_security_identifier_validity", "CHECK", ("valid_to", ">=", "valid_from")),
        (
            "fk_security_identifiers_security",
            "FOREIGN KEY",
            ("foreignkey(security_id)referencessecurities(id)ondelete cascade",),
        ),
        (
            "uq_security_identifier_scoped_start",
            "UNIQUE",
            ("unique(namespace,exchange,normalized_value,valid_from)",),
        ),
    ),
    "private_files": (
        ("private_files_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        ("uq_private_file_content_hash", "UNIQUE", ("unique(content_hash)",)),
        ("uq_private_file_storage_key", "UNIQUE", ("unique(storage_key)",)),
    ),
    "imports": (
        ("imports_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "ck_import_scope",
            "CHECK",
            ("kind", "account_id", "fund_security_id", "positions", "fund"),
        ),
        ("uq_import_idempotency_key", "UNIQUE", ("unique(idempotency_key)",)),
        (
            "imports_account_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
        ),
        (
            "imports_duplicate_of_import_id_fkey",
            "FOREIGN KEY",
            (
                "foreignkey(duplicate_of_import_id)referencesimports(id)"
                "ondelete set null",
            ),
        ),
        (
            "imports_file_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(file_id)referencesprivate_files(id)ondelete restrict",),
        ),
        (
            "imports_fund_security_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(fund_security_id)referencessecurities(id)ondelete restrict",),
        ),
        (
            "imports_published_snapshot_id_fkey",
            "FOREIGN KEY",
            (
                "foreignkey(published_snapshot_id)referencesposition_snapshots(id)"
                "ondelete set null",
            ),
        ),
        (
            "imports_staging_snapshot_id_fkey",
            "FOREIGN KEY",
            (
                "foreignkey(staging_snapshot_id)referencesposition_snapshots(id)"
                "ondelete set null",
            ),
        ),
    ),
    "import_batches": (
        ("import_batches_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "import_batches_import_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(import_id)referencesimports(id)ondelete cascade",),
        ),
        (
            "uq_import_batch_identity",
            "UNIQUE",
            ("unique(import_id,purpose,review_revision,ordinal)",),
        ),
    ),
    "import_rows": (
        ("import_rows_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "import_rows_import_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(import_id)referencesimports(id)ondelete cascade",),
        ),
        (
            "import_rows_security_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
        ),
        (
            "uq_import_row_number",
            "UNIQUE",
            ("unique(import_id,row_number)",),
        ),
    ),
    "import_review_events": (
        ("import_review_events_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "import_review_events_import_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(import_id)referencesimports(id)ondelete cascade",),
        ),
        (
            "uq_import_review_revision",
            "UNIQUE",
            ("unique(import_id,review_revision)",),
        ),
    ),
    "security_issuer_mapping_events": (
        ("security_issuer_mapping_events_pkey", "PRIMARY KEY", ("primarykey(id)",)),
        (
            "security_issuer_mapping_events_security_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
        ),
        (
            "security_issuer_mapping_events_new_issuer_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(new_issuer_id)referencesissuers(id)ondelete set null",),
        ),
        (
            "security_issuer_mapping_events_previous_issuer_id_fkey",
            "FOREIGN KEY",
            ("foreignkey(previous_issuer_id)referencesissuers(id)ondelete set null",),
        ),
    ),
}

# Later DSQL migrations add or replace some core-table objects. They are
# allowed while validating the original create-table step, but each is still
# validated by its own ALTER/index/constraint step before that migration is
# recorded. This lets the runner safely revalidate a completed 0001 step after
# the schema has advanced to 0003.
TABLE_EVOLUTIONS: dict[
    str,
    tuple[
        tuple[ColumnSignature, ...],
        tuple[ConstraintSignature, ...],
        frozenset[str],
    ],
] = {
    "accounts": (
        (
            ("current_position_revision", "integer", "NO", None, None, None),
            ("current_position_snapshot_id", "uuid", "YES", None, None, None),
        ),
        (
            (
                "fk_accounts_current_position_snapshot",
                "FOREIGN KEY",
                (
                    "foreignkey(current_position_snapshot_id)referencesposition_snapshots(id)ondeleterestrict",
                ),
            ),
        ),
        frozenset(),
    ),
    "issuer_aliases": (
        (
            ("alias_namespace", "character varying", "NO", 40, None, None),
            ("review_status", "character varying", "NO", 24, None, None),
        ),
        (
            (
                "uq_issuer_alias_scoped",
                "UNIQUE",
                ("unique(issuer_id,alias_namespace,normalized_alias)",),
            ),
        ),
        frozenset({"uq_issuer_alias"}),
    ),
    "position_snapshots": (
        (("revision", "integer", "NO", None, None, None),),
        (
            (
                "uq_position_snapshot_revision",
                "UNIQUE",
                ("unique(account_id,source,revision)",),
            ),
        ),
        frozenset({"uq_position_snapshot_identity"}),
    ),
}


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
                expected_index_table=table_name,
                expected_index_columns=columns,
            )
            for name, table_name, columns, statement in (
                (
                    "ix_issuer_aliases_normalized_alias",
                    "issuer_aliases",
                    ("normalized_alias",),
                    "CREATE INDEX ASYNC ix_issuer_aliases_normalized_alias "
                    "ON issuer_aliases (normalized_alias)",
                ),
                (
                    "ix_position_snapshots_account_asof",
                    "position_snapshots",
                    ("account_id", "snapshot_at"),
                    "CREATE INDEX ASYNC ix_position_snapshots_account_asof "
                    "ON position_snapshots (account_id, snapshot_at)",
                ),
                (
                    "ix_quotes_security_asof",
                    "quotes",
                    ("security_id", "as_of"),
                    "CREATE INDEX ASYNC ix_quotes_security_asof "
                    "ON quotes (security_id, as_of)",
                ),
                (
                    "ix_position_lines_snapshot",
                    "position_snapshot_lines",
                    ("snapshot_id",),
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
            expected_column=("integer", "NO", "0"),
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
            expected_column=("integer", "NO", "1"),
        ),
    ),
)

IMMUTABLE_POSITION_REVISIONS_AND_IDENTIFIERS = DsqlMigration(
    revision="0003_immutable_position_revisions_and_identifiers",
    steps=(
        DsqlMigrationStep(
            "add_account_current_position_snapshot",
            "alter",
            "ALTER TABLE accounts ADD COLUMN current_position_snapshot_id uuid",
            "accounts.current_position_snapshot_id",
            "SELECT true",
            expected_column=("uuid", "YES", None),
        ),
        DsqlMigrationStep(
            "add_issuer_alias_namespace",
            "alter",
            "ALTER TABLE issuer_aliases ADD COLUMN alias_namespace varchar(40) "
            "NOT NULL DEFAULT 'name'",
            "issuer_aliases.alias_namespace",
            "SELECT true",
            expected_column=("character varying", "NO", "%name%"),
        ),
        DsqlMigrationStep(
            "add_issuer_alias_review_status",
            "alter",
            "ALTER TABLE issuer_aliases ADD COLUMN review_status varchar(24) "
            "NOT NULL DEFAULT 'unreviewed'",
            "issuer_aliases.review_status",
            "SELECT true",
            expected_column=("character varying", "NO", "%unreviewed%"),
        ),
        DsqlMigrationStep(
            "create_security_identifiers",
            "table",
            """CREATE TABLE security_identifiers (
                id uuid NOT NULL,
                security_id uuid NOT NULL,
                namespace varchar(40) NOT NULL,
                exchange varchar(40) NOT NULL,
                value varchar(128) NOT NULL,
                normalized_value varchar(128) NOT NULL,
                valid_from date NOT NULL,
                valid_to date,
                source varchar(100) NOT NULL,
                review_status varchar(24) NOT NULL,
                CONSTRAINT security_identifiers_pkey PRIMARY KEY (id),
                CONSTRAINT ck_security_identifier_validity
                    CHECK (valid_to IS NULL OR valid_to >= valid_from),
                CONSTRAINT fk_security_identifiers_security FOREIGN KEY (security_id)
                    REFERENCES securities (id) ON DELETE CASCADE,
                CONSTRAINT uq_security_identifier_scoped_start
                    UNIQUE (namespace, exchange, normalized_value, valid_from)
            )""",
            "security_identifiers",
            "SELECT true",
        ),
        DsqlMigrationStep(
            "drop_position_snapshot_effective_date_identity",
            "drop_constraint",
            "ALTER TABLE position_snapshots DROP CONSTRAINT "
            "uq_position_snapshot_identity",
            "position_snapshots.uq_position_snapshot_identity",
            "SELECT true",
            expected_constraint=(
                "position_snapshots",
                "uq_position_snapshot_identity",
                "UNIQUE",
                ("unique(account_id,snapshot_at,source)",),
            ),
        ),
        DsqlMigrationStep(
            "drop_issuer_alias_unscoped_identity",
            "drop_constraint",
            "ALTER TABLE issuer_aliases DROP CONSTRAINT uq_issuer_alias",
            "issuer_aliases.uq_issuer_alias",
            "SELECT true",
            expected_constraint=(
                "issuer_aliases",
                "uq_issuer_alias",
                "UNIQUE",
                ("unique(issuer_id,normalized_alias)",),
            ),
        ),
        DsqlMigrationStep(
            "backfill_immutable_position_revisions",
            "backfill",
            "DML backfill manual snapshot revisions, selected pointers, and "
            "counters in batches",
            "position_snapshots",
            "SELECT true",
        ),
        DsqlMigrationStep(
            "add_current_snapshot_foreign_key",
            "add_constraint",
            "ALTER TABLE accounts ADD CONSTRAINT fk_accounts_current_position_snapshot "
            "FOREIGN KEY (current_position_snapshot_id) REFERENCES "
            "position_snapshots (id) "
            "ON DELETE RESTRICT NOT VALID",
            "accounts.fk_accounts_current_position_snapshot",
            "SELECT true",
            expected_constraint=(
                "accounts",
                "fk_accounts_current_position_snapshot",
                "FOREIGN KEY",
                (
                    "foreignkey(current_position_snapshot_id)references"
                    "position_snapshots(id)ondelete restrict",
                ),
            ),
            expected_constraint_validated=False,
        ),
        DsqlMigrationStep(
            "validate_current_snapshot_foreign_key",
            "async_alter",
            "ALTER TABLE ASYNC accounts VALIDATE CONSTRAINT "
            "fk_accounts_current_position_snapshot",
            "accounts.fk_accounts_current_position_snapshot",
            "SELECT true",
            expected_constraint=(
                "accounts",
                "fk_accounts_current_position_snapshot",
                "FOREIGN KEY",
                (
                    "foreignkey(current_position_snapshot_id)references"
                    "position_snapshots(id)ondelete restrict",
                ),
            ),
            expected_constraint_validated=True,
        ),
        DsqlMigrationStep(
            "create_position_revision_unique_index",
            "index",
            "CREATE UNIQUE INDEX ASYNC uq_position_snapshot_revision "
            "ON position_snapshots (account_id, source, revision)",
            "uq_position_snapshot_revision",
            "SELECT true",
            expected_index_table="position_snapshots",
            expected_index_columns=("account_id", "source", "revision"),
            expected_index_unique=True,
        ),
        DsqlMigrationStep(
            "attach_position_revision_unique_constraint",
            "add_constraint",
            "ALTER TABLE position_snapshots ADD CONSTRAINT "
            "uq_position_snapshot_revision UNIQUE USING INDEX "
            "uq_position_snapshot_revision",
            "position_snapshots.uq_position_snapshot_revision",
            "SELECT true",
            expected_constraint=(
                "position_snapshots",
                "uq_position_snapshot_revision",
                "UNIQUE",
                ("unique(account_id,source,revision)",),
            ),
            expected_constraint_validated=True,
        ),
        DsqlMigrationStep(
            "create_scoped_issuer_alias_unique_index",
            "index",
            "CREATE UNIQUE INDEX ASYNC uq_issuer_alias_scoped "
            "ON issuer_aliases (issuer_id, alias_namespace, normalized_alias)",
            "uq_issuer_alias_scoped",
            "SELECT true",
            expected_index_table="issuer_aliases",
            expected_index_columns=("issuer_id", "alias_namespace", "normalized_alias"),
            expected_index_unique=True,
        ),
        DsqlMigrationStep(
            "attach_scoped_issuer_alias_unique_constraint",
            "add_constraint",
            "ALTER TABLE issuer_aliases ADD CONSTRAINT uq_issuer_alias_scoped "
            "UNIQUE USING INDEX uq_issuer_alias_scoped",
            "issuer_aliases.uq_issuer_alias_scoped",
            "SELECT true",
            expected_constraint=(
                "issuer_aliases",
                "uq_issuer_alias_scoped",
                "UNIQUE",
                ("unique(issuer_id,alias_namespace,normalized_alias)",),
            ),
            expected_constraint_validated=True,
        ),
        DsqlMigrationStep(
            "create_security_identifier_security_index",
            "index",
            "CREATE INDEX ASYNC ix_security_identifiers_security "
            "ON security_identifiers (security_id)",
            "ix_security_identifiers_security",
            "SELECT true",
            expected_index_table="security_identifiers",
            expected_index_columns=("security_id",),
        ),
    ),
)

STAGE1_POSITION_IMPORTS = DsqlMigration(
    revision="0004_stage1_position_imports",
    steps=(
        DsqlMigrationStep(
            "create_private_files",
            "table",
            """CREATE TABLE private_files (
                id uuid NOT NULL,
                content_hash varchar(64) NOT NULL,
                storage_key varchar(100) NOT NULL,
                original_name varchar(200) NOT NULL,
                content_type varchar(100) NOT NULL,
                byte_size integer NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT private_files_pkey PRIMARY KEY (id),
                CONSTRAINT uq_private_file_content_hash UNIQUE (content_hash),
                CONSTRAINT uq_private_file_storage_key UNIQUE (storage_key)
            )""",
            "private_files",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_imports",
            "table",
            """CREATE TABLE imports (
                id uuid NOT NULL,
                file_id uuid NOT NULL,
                kind varchar(20) NOT NULL,
                account_id uuid,
                fund_security_id uuid,
                effective_date date NOT NULL,
                source_label varchar(100) NOT NULL,
                parser_version varchar(80) NOT NULL,
                column_mapping jsonb NOT NULL,
                file_sha256 varchar(64) NOT NULL,
                identity_hash varchar(64) NOT NULL,
                interpretation_hash varchar(64) NOT NULL,
                payload_hash varchar(64),
                status varchar(24) NOT NULL,
                review_revision integer NOT NULL DEFAULT 1,
                expected_account_revision integer,
                idempotency_key varchar(128) NOT NULL,
                row_count integer NOT NULL,
                batch_count integer NOT NULL,
                duplicate_of_import_id uuid,
                staging_snapshot_id uuid,
                published_snapshot_id uuid,
                diagnostics jsonb NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT imports_pkey PRIMARY KEY (id),
                CONSTRAINT ck_import_scope CHECK (
                    (kind = 'positions' AND account_id IS NOT NULL
                        AND fund_security_id IS NULL) OR
                    (kind = 'fund' AND account_id IS NULL
                        AND fund_security_id IS NOT NULL)
                ),
                CONSTRAINT uq_import_idempotency_key UNIQUE (idempotency_key),
                CONSTRAINT imports_account_id_fkey FOREIGN KEY (account_id)
                    REFERENCES accounts (id) ON DELETE RESTRICT,
                CONSTRAINT imports_duplicate_of_import_id_fkey
                    FOREIGN KEY (duplicate_of_import_id)
                    REFERENCES imports (id) ON DELETE SET NULL,
                CONSTRAINT imports_file_id_fkey FOREIGN KEY (file_id)
                    REFERENCES private_files (id) ON DELETE RESTRICT,
                CONSTRAINT imports_fund_security_id_fkey FOREIGN KEY (fund_security_id)
                    REFERENCES securities (id) ON DELETE RESTRICT,
                CONSTRAINT imports_published_snapshot_id_fkey
                    FOREIGN KEY (published_snapshot_id)
                    REFERENCES position_snapshots (id) ON DELETE SET NULL,
                CONSTRAINT imports_staging_snapshot_id_fkey
                    FOREIGN KEY (staging_snapshot_id)
                    REFERENCES position_snapshots (id) ON DELETE SET NULL
            )""",
            "imports",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_security_issuer_mapping_events",
            "table",
            """CREATE TABLE security_issuer_mapping_events (
                id uuid NOT NULL,
                security_id uuid NOT NULL,
                previous_issuer_id uuid,
                new_issuer_id uuid,
                reason varchar(500) NOT NULL,
                changed_at timestamptz NOT NULL,
                CONSTRAINT security_issuer_mapping_events_pkey PRIMARY KEY (id),
                CONSTRAINT security_issuer_mapping_events_security_id_fkey
                    FOREIGN KEY (security_id)
                    REFERENCES securities (id) ON DELETE RESTRICT,
                CONSTRAINT security_issuer_mapping_events_new_issuer_id_fkey
                    FOREIGN KEY (new_issuer_id)
                    REFERENCES issuers (id) ON DELETE SET NULL,
                CONSTRAINT security_issuer_mapping_events_previous_issuer_id_fkey
                    FOREIGN KEY (previous_issuer_id)
                    REFERENCES issuers (id) ON DELETE SET NULL
            )""",
            "security_issuer_mapping_events",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_import_batches",
            "table",
            """CREATE TABLE import_batches (
                id uuid NOT NULL,
                import_id uuid NOT NULL,
                purpose varchar(32) NOT NULL,
                review_revision integer NOT NULL,
                ordinal integer NOT NULL,
                payload_hash varchar(64) NOT NULL,
                row_count integer NOT NULL,
                status varchar(24) NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT import_batches_pkey PRIMARY KEY (id),
                CONSTRAINT import_batches_import_id_fkey FOREIGN KEY (import_id)
                    REFERENCES imports (id) ON DELETE CASCADE,
                CONSTRAINT uq_import_batch_identity
                    UNIQUE (import_id, purpose, review_revision, ordinal)
            )""",
            "import_batches",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_import_rows",
            "table",
            """CREATE TABLE import_rows (
                id uuid NOT NULL,
                import_id uuid NOT NULL,
                row_number integer NOT NULL,
                raw_payload jsonb NOT NULL,
                raw_identifier varchar(2000),
                raw_name varchar(2000),
                raw_asset_type varchar(2000),
                raw_quantity varchar(2000),
                raw_price varchar(2000),
                raw_currency varchar(200),
                raw_weight_value varchar(100),
                raw_weight_unit varchar(24),
                security_id uuid,
                normalized_quantity numeric(28, 10),
                normalized_price numeric(24, 10),
                normalized_weight numeric(18, 10),
                currency varchar(3),
                row_status varchar(24) NOT NULL,
                excluded boolean NOT NULL,
                correction_reason text,
                diagnostics jsonb NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT import_rows_pkey PRIMARY KEY (id),
                CONSTRAINT import_rows_import_id_fkey FOREIGN KEY (import_id)
                    REFERENCES imports (id) ON DELETE CASCADE,
                CONSTRAINT import_rows_security_id_fkey FOREIGN KEY (security_id)
                    REFERENCES securities (id) ON DELETE RESTRICT,
                CONSTRAINT uq_import_row_number UNIQUE (import_id, row_number)
            )""",
            "import_rows",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_import_review_events",
            "table",
            """CREATE TABLE import_review_events (
                id uuid NOT NULL,
                import_id uuid NOT NULL,
                review_revision integer NOT NULL,
                action varchar(32) NOT NULL,
                reason varchar(500) NOT NULL,
                change_payload jsonb NOT NULL,
                created_at timestamptz NOT NULL,
                CONSTRAINT import_review_events_pkey PRIMARY KEY (id),
                CONSTRAINT import_review_events_import_id_fkey FOREIGN KEY (import_id)
                    REFERENCES imports (id) ON DELETE CASCADE,
                CONSTRAINT uq_import_review_revision UNIQUE (import_id, review_revision)
            )""",
            "import_review_events",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        *(
            DsqlMigrationStep(
                f"create_index_{name}",
                "index",
                f"CREATE INDEX ASYNC {name} ON {table_name} ({', '.join(columns)})",
                name,
                """SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_index i
                    JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = current_schema()
                      AND c.relname = :object_name
                      AND i.indisvalid
                )""",
                expected_index_table=table_name,
                expected_index_columns=columns,
            )
            for name, table_name, columns in (
                ("ix_imports_file", "imports", ("file_id",)),
                (
                    "ix_imports_identity",
                    "imports",
                    ("identity_hash", "interpretation_hash"),
                ),
                (
                    "ix_import_batches_import",
                    "import_batches",
                    ("import_id", "purpose"),
                ),
                (
                    "ix_import_rows_import_status",
                    "import_rows",
                    ("import_id", "row_status"),
                ),
            )
        ),
    ),
)


# Versioned Stage 1 fund schema: statements frozen at generation time.
TABLE_COLUMNS["fund_snapshots"] = (
    ("id", "uuid", "NO", None, None, None),
    ("fund_security_id", "uuid", "NO", None, None, None),
    ("import_id", "uuid", "NO", None, None, None),
    ("review_revision", "integer", "NO", None, None, None),
    ("as_of", "date", "NO", None, None, None),
    ("fetched_at", "timestamp with time zone", "NO", None, None, None),
    ("source", "character varying", "NO", 100, None, None),
    ("source_url", "character varying", "YES", 500, None, None),
    ("parser_version", "character varying", "NO", 80, None, None),
    ("content_hash", "character varying", "NO", 64, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("reported_weight", "numeric", "NO", None, 18, 10),
    ("recognized_weight", "numeric", "NO", None, 18, 10),
    ("quality_status", "character varying", "NO", 24, None, None),
    ("diagnostics", "jsonb", "NO", None, None, None),
    ("published_at", "timestamp with time zone", "YES", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["fund_snapshots"] = (
    (
        "fund_snapshots_fund_security_id_fkey",
        "FOREIGN KEY",
        (("foreignkey(fund_security_id)referencessecurities(id)ondeleteRESTRICT"),),
    ),
    (
        "fund_snapshots_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_id)referencesimports(id)ondeleteRESTRICT",),
    ),
    ("fund_snapshots_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    ("uq_fund_import_revision", "UNIQUE", ("unique(import_id,review_revision)",)),
)
TABLE_COLUMNS["fund_lines"] = (
    ("id", "uuid", "NO", None, None, None),
    ("snapshot_id", "uuid", "NO", None, None, None),
    ("row_number", "integer", "NO", None, None, None),
    ("review_row_id", "uuid", "NO", None, None, None),
    ("security_id", "uuid", "YES", None, None, None),
    ("weight", "numeric", "NO", None, 18, 10),
    ("asset_type", "character varying", "NO", 24, None, None),
    ("raw_identifier", "character varying", "YES", 2000, None, None),
    ("raw_name", "character varying", "YES", 2000, None, None),
    ("match_status", "character varying", "NO", 24, None, None),
)
TABLE_CONSTRAINTS["fund_lines"] = (
    ("fund_lines_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "fund_lines_review_row_id_fkey",
        "FOREIGN KEY",
        (("foreignkey(review_row_id)referencesimport_rows(id)ondeleteRESTRICT"),),
    ),
    (
        "fund_lines_security_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(security_id)referencessecurities(id)ondeleteRESTRICT",),
    ),
    (
        "fund_lines_snapshot_id_fkey",
        "FOREIGN KEY",
        (("foreignkey(snapshot_id)referencesfund_snapshots(id)ondeleteCASCADE"),),
    ),
    ("uq_fund_line_row", "UNIQUE", ("unique(snapshot_id,row_number)",)),
)
STAGE1_FUND_COMPOSITIONS = DsqlMigration(
    "0005_fund_compositions",
    (
        DsqlMigrationStep(
            "create_fund_snapshots",
            "table",
            """CREATE TABLE fund_snapshots (
	id UUID NOT NULL,
	fund_security_id UUID NOT NULL,
	import_id UUID NOT NULL,
	review_revision INTEGER NOT NULL,
	as_of DATE NOT NULL,
	fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
	source VARCHAR(100) NOT NULL,
	source_url VARCHAR(500),
	parser_version VARCHAR(80) NOT NULL,
	content_hash VARCHAR(64) NOT NULL,
	status VARCHAR(24) NOT NULL,
	reported_weight NUMERIC(18, 10) NOT NULL,
	recognized_weight NUMERIC(18, 10) NOT NULL,
	quality_status VARCHAR(24) NOT NULL,
	diagnostics JSONB NOT NULL,
	published_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT fund_snapshots_pkey PRIMARY KEY (id),
	CONSTRAINT uq_fund_import_revision UNIQUE (import_id, review_revision),
	CONSTRAINT fund_snapshots_fund_security_id_fkey FOREIGN KEY(fund_security_id)
    REFERENCES securities (id) ON DELETE RESTRICT,
	CONSTRAINT fund_snapshots_import_id_fkey FOREIGN KEY(import_id)
    REFERENCES imports (id) ON DELETE RESTRICT
)""",
            "fund_snapshots",
            (
                "SELECT EXISTS (SELECT 1 FROM information_schema."
                "tables WHERE table_schema = current_schema() AND"
                " table_name = :object_name)"
            ),
        ),
        DsqlMigrationStep(
            "ix_fund_snapshots_selection",
            "index",
            (
                "CREATE INDEX ASYNC ix_fund_snapshots_selection O"
                "N fund_snapshots (fund_security_id, as_of, statu"
                "s)"
            ),
            "ix_fund_snapshots_selection",
            "SELECT 1",
            expected_index_table="fund_snapshots",
            expected_index_columns=("fund_security_id", "as_of", "status"),
        ),
        DsqlMigrationStep(
            "create_fund_lines",
            "table",
            """CREATE TABLE fund_lines (
	id UUID NOT NULL,
	snapshot_id UUID NOT NULL,
	row_number INTEGER NOT NULL,
	review_row_id UUID NOT NULL,
	security_id UUID,
	weight NUMERIC(18, 10) NOT NULL,
	asset_type VARCHAR(24) NOT NULL,
	raw_identifier VARCHAR(2000),
	raw_name VARCHAR(2000),
	match_status VARCHAR(24) NOT NULL,
	CONSTRAINT fund_lines_pkey PRIMARY KEY (id),
	CONSTRAINT uq_fund_line_row UNIQUE (snapshot_id, row_number),
	CONSTRAINT fund_lines_snapshot_id_fkey FOREIGN KEY(snapshot_id)
    REFERENCES fund_snapshots (id) ON DELETE CASCADE,
	CONSTRAINT fund_lines_review_row_id_fkey FOREIGN KEY(review_row_id)
    REFERENCES import_rows (id) ON DELETE RESTRICT,
	CONSTRAINT fund_lines_security_id_fkey FOREIGN KEY(security_id)
    REFERENCES securities (id) ON DELETE RESTRICT
)""",
            "fund_lines",
            (
                "SELECT EXISTS (SELECT 1 FROM information_schema."
                "tables WHERE table_schema = current_schema() AND"
                " table_name = :object_name)"
            ),
        ),
        DsqlMigrationStep(
            "ix_fund_lines_snapshot",
            "index",
            ("CREATE INDEX ASYNC ix_fund_lines_snapshot ON fund_lines (snapshot_id)"),
            "ix_fund_lines_snapshot",
            "SELECT 1",
            expected_index_table="fund_lines",
            expected_index_columns=("snapshot_id",),
        ),
    ),
)

TABLE_COLUMNS["portfolio_calculations"] = (
    ("id", "uuid", "NO", None, None, None),
    ("storage_key", "character varying", "NO", 100, None, None),
    ("content_hash", "character varying", "NO", 64, None, None),
    ("input_hash", "character varying", "NO", 64, None, None),
    ("calculation_version", "character varying", "NO", 80, None, None),
    ("generated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["portfolio_calculations"] = (
    ("portfolio_calculations_pkey", "PRIMARY KEY", ("primarykey(id)",)),
)
STAGE1_REPORTS = DsqlMigration(
    "0006_portfolio_reports",
    (
        DsqlMigrationStep(
            "create_portfolio_calculations",
            "table",
            """CREATE TABLE portfolio_calculations (
        id uuid NOT NULL,
        storage_key varchar(100) NOT NULL,
        content_hash varchar(64) NOT NULL,
        input_hash varchar(64) NOT NULL,
        calculation_version varchar(80) NOT NULL,
        generated_at timestamptz NOT NULL,
        CONSTRAINT portfolio_calculations_pkey PRIMARY KEY (id)
    )""",
            "portfolio_calculations",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
    ),
)

TABLE_COLUMNS["document_imports"] = (
    ("id", "uuid", "NO", None, None, None),
    ("file_id", "uuid", "NO", None, None, None),
    ("position_import_id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("effective_date", "date", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("parser_version", "character varying", "NO", 80, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("row_count", "integer", "NO", None, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("diagnostics", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["document_imports"] = (
    ("document_imports_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "document_imports_file_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(file_id)referencesprivate_files(id)ondeleterestrict",),
    ),
    (
        "document_imports_position_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(position_import_id)referencesimports(id)ondeleterestrict",),
    ),
    (
        "document_imports_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondeleterestrict",),
    ),
    (
        "uq_document_import_link",
        "UNIQUE",
        ("unique(file_id,position_import_id)",),
    ),
    (
        "uq_document_import_idempotency",
        "UNIQUE",
        ("unique(idempotency_key)",),
    ),
)
STAGE2_DOCUMENT_INGESTION = DsqlMigration(
    "0007_stage2_document_ingestion",
    (
        DsqlMigrationStep(
            "create_document_imports",
            "table",
            """CREATE TABLE document_imports (
        id uuid NOT NULL,
        file_id uuid NOT NULL,
        position_import_id uuid NOT NULL,
        account_id uuid NOT NULL,
        effective_date date NOT NULL,
        source_label varchar(100) NOT NULL,
        parser_version varchar(80) NOT NULL,
        idempotency_key varchar(128) NOT NULL,
        row_count integer NOT NULL,
        status varchar(24) NOT NULL,
        diagnostics jsonb NOT NULL,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        CONSTRAINT document_imports_pkey PRIMARY KEY (id),
        CONSTRAINT document_imports_file_id_fkey FOREIGN KEY (file_id)
            REFERENCES private_files(id) ON DELETE RESTRICT,
        CONSTRAINT document_imports_position_import_id_fkey
            FOREIGN KEY (position_import_id) REFERENCES imports(id) ON DELETE RESTRICT,
        CONSTRAINT document_imports_account_id_fkey FOREIGN KEY (account_id)
            REFERENCES accounts(id) ON DELETE RESTRICT,
        CONSTRAINT uq_document_import_link UNIQUE (file_id, position_import_id),
        CONSTRAINT uq_document_import_idempotency UNIQUE (idempotency_key)
    )""",
            "document_imports",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
    ),
)

TABLE_COLUMNS["spending_categories"] = (
    ("id", "uuid", "NO", None, None, None),
    ("slug", "character varying", "NO", 80, None, None),
    ("display_name", "character varying", "NO", 120, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["spending_categories"] = (
    ("spending_categories_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    ("uq_spending_category_slug", "UNIQUE", ("unique(slug)",)),
)
TABLE_COLUMNS["transaction_imports"] = (
    ("id", "uuid", "NO", None, None, None),
    ("file_id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("parser_version", "character varying", "NO", 80, None, None),
    ("file_sha256", "character varying", "NO", 64, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("statement_start", "date", "YES", None, None, None),
    ("statement_end", "date", "YES", None, None, None),
    ("review_revision", "integer", "NO", None, None, None),
    ("row_count", "integer", "NO", None, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("diagnostics", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["transaction_imports"] = (
    ("transaction_imports_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    ("uq_transaction_import_idempotency", "UNIQUE", ("unique(idempotency_key)",)),
    (
        "transaction_imports_file_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(file_id)referencesprivate_files(id)ondelete restrict",),
    ),
    (
        "transaction_imports_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
)
TABLE_COLUMNS["financial_transactions"] = (
    ("id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("import_id", "uuid", "YES", None, None, None),
    ("row_number", "integer", "YES", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("provider_transaction_id", "character varying", "YES", 200, None, None),
    ("raw_posted_date", "character varying", "YES", 100, None, None),
    ("posted_date", "date", "YES", None, None, None),
    ("raw_transaction_date", "character varying", "YES", 100, None, None),
    ("transaction_date", "date", "YES", None, None, None),
    ("raw_amount", "character varying", "YES", 100, None, None),
    ("amount", "numeric", "YES", None, 24, 10),
    ("raw_currency", "character varying", "YES", 40, None, None),
    ("currency", "character varying", "YES", 3, None, None),
    ("raw_description", "text", "NO", None, None, None),
    ("description", "text", "NO", None, None, None),
    ("normalized_merchant", "character varying", "NO", 200, None, None),
    ("raw_type", "character varying", "YES", 120, None, None),
    ("raw_payload", "jsonb", "NO", None, None, None),
    ("fingerprint", "character varying", "NO", 64, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("identity_resolution", "character varying", "YES", 24, None, None),
    ("duplicate_of_transaction_id", "uuid", "YES", None, None, None),
    ("classification", "character varying", "NO", 24, None, None),
    ("category_id", "uuid", "YES", None, None, None),
    ("category_source", "character varying", "NO", 24, None, None),
    ("revision", "integer", "NO", None, None, None),
    ("idempotency_key", "character varying", "YES", 128, None, None),
    ("diagnostics", "jsonb", "NO", None, None, None),
    ("published_at", "timestamp with time zone", "YES", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["financial_transactions"] = (
    ("financial_transactions_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "uq_transaction_import_row",
        "UNIQUE",
        ("unique(import_id,row_number)",),
    ),
    (
        "financial_transactions_idempotency_key_key",
        "UNIQUE",
        ("unique(idempotency_key)",),
    ),
    (
        "financial_transactions_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "financial_transactions_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_id)referencestransaction_imports(id)ondelete restrict",),
    ),
    (
        "financial_transactions_category_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(category_id)referencesspending_categories(id)ondelete set null",),
    ),
    (
        "financial_transactions_duplicate_of_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(duplicate_of_transaction_id)"
            "referencesfinancial_transactions(id)ondelete set null",
        ),
    ),
)
TABLE_COLUMNS["transaction_provider_identities"] = (
    ("id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("provider_transaction_id", "character varying", "NO", 200, None, None),
    ("transaction_id", "uuid", "NO", None, None, None),
)
TABLE_CONSTRAINTS["transaction_provider_identities"] = (
    ("transaction_provider_identities_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "uq_transaction_provider_identity",
        "UNIQUE",
        ("unique(account_id,source_label,provider_transaction_id)",),
    ),
    (
        "uq_transaction_provider_transaction",
        "UNIQUE",
        ("unique(transaction_id)",),
    ),
    (
        "transaction_provider_identities_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "transaction_provider_identities_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(transaction_id)"
            "referencesfinancial_transactions(id)ondelete cascade",
        ),
    ),
)
TABLE_COLUMNS["merchant_category_rules"] = (
    ("id", "uuid", "NO", None, None, None),
    ("normalized_merchant", "character varying", "NO", 200, None, None),
    ("category_id", "uuid", "NO", None, None, None),
    ("priority", "integer", "NO", None, None, None),
    ("version", "integer", "NO", None, None, None),
    ("active", "boolean", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["merchant_category_rules"] = (
    ("merchant_category_rules_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "uq_merchant_category_rule_version",
        "UNIQUE",
        ("unique(normalized_merchant,version)",),
    ),
    (
        "merchant_category_rules_category_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(category_id)referencesspending_categories(id)ondelete restrict",),
    ),
)
TABLE_COLUMNS["transaction_review_events"] = (
    ("id", "uuid", "NO", None, None, None),
    ("transaction_id", "uuid", "NO", None, None, None),
    ("import_id", "uuid", "YES", None, None, None),
    ("review_revision", "integer", "NO", None, None, None),
    ("action", "character varying", "NO", 32, None, None),
    ("reason", "character varying", "NO", 500, None, None),
    ("change_payload", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["transaction_review_events"] = (
    ("transaction_review_events_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "transaction_review_events_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(transaction_id)"
            "referencesfinancial_transactions(id)ondelete cascade",
        ),
    ),
    (
        "transaction_review_events_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_id)referencestransaction_imports(id)ondelete cascade",),
    ),
)
TABLE_COLUMNS["transaction_splits"] = (
    ("id", "uuid", "NO", None, None, None),
    ("transaction_id", "uuid", "NO", None, None, None),
    ("split_index", "integer", "NO", None, None, None),
    ("amount", "numeric", "NO", None, 24, 10),
    ("category_id", "uuid", "YES", None, None, None),
    ("note", "character varying", "YES", 500, None, None),
    ("revision", "integer", "NO", None, None, None),
)
TABLE_CONSTRAINTS["transaction_splits"] = (
    ("transaction_splits_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "uq_transaction_split_index",
        "UNIQUE",
        ("unique(transaction_id,split_index)",),
    ),
    (
        "transaction_splits_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(transaction_id)"
            "referencesfinancial_transactions(id)ondelete cascade",
        ),
    ),
    (
        "transaction_splits_category_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(category_id)referencesspending_categories(id)ondelete set null",),
    ),
)
TABLE_COLUMNS["transfer_matches"] = (
    ("id", "uuid", "NO", None, None, None),
    ("first_transaction_id", "uuid", "NO", None, None, None),
    ("second_transaction_id", "uuid", "NO", None, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("match_method", "character varying", "NO", 32, None, None),
    ("reason", "character varying", "NO", 500, None, None),
    ("confirmed_at", "timestamp with time zone", "YES", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["transfer_matches"] = (
    ("transfer_matches_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "transfer_matches_first_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(first_transaction_id)"
            "referencesfinancial_transactions(id)ondelete restrict",
        ),
    ),
    (
        "transfer_matches_second_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(second_transaction_id)"
            "referencesfinancial_transactions(id)ondelete restrict",
        ),
    ),
)
TABLE_COLUMNS["active_transfer_transactions"] = (
    ("transaction_id", "uuid", "NO", None, None, None),
    ("transfer_id", "uuid", "NO", None, None, None),
)
TABLE_CONSTRAINTS["active_transfer_transactions"] = (
    (
        "active_transfer_transactions_pkey",
        "PRIMARY KEY",
        ("primarykey(transaction_id)",),
    ),
    (
        "active_transfer_transactions_transaction_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(transaction_id)"
            "referencesfinancial_transactions(id)ondelete restrict",
        ),
    ),
    (
        "active_transfer_transactions_transfer_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(transfer_id)referencestransfer_matches(id)ondelete cascade",),
    ),
)
TABLE_COLUMNS["account_balance_observations"] = (
    ("id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("as_of", "date", "NO", None, None, None),
    ("revision", "integer", "NO", None, None, None),
    ("balance_kind", "character varying", "NO", 12, None, None),
    ("amount", "numeric", "NO", None, 24, 10),
    ("currency", "character varying", "NO", 3, None, None),
    ("source", "character varying", "NO", 100, None, None),
    ("quality_status", "character varying", "NO", 24, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["account_balance_observations"] = (
    (
        "account_balance_observations_pkey",
        "PRIMARY KEY",
        ("primarykey(id)",),
    ),
    ("ck_account_balance_nonnegative", "CHECK", ("amount", ">=", "0")),
    (
        "account_balance_observations_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "uq_account_balance_revision",
        "UNIQUE",
        ("unique(account_id,as_of,revision)",),
    ),
    (
        "uq_account_balance_idempotency",
        "UNIQUE",
        ("unique(idempotency_key)",),
    ),
)
TABLE_COLUMNS["jobs"] = (
    ("id", "uuid", "NO", None, None, None),
    ("job_type", "character varying", "NO", 64, None, None),
    ("account_id", "uuid", "YES", None, None, None),
    ("input_file_id", "uuid", "YES", None, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("payload", "jsonb", "NO", None, None, None),
    ("result", "jsonb", "YES", None, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("attempts", "integer", "NO", None, None, None),
    ("max_attempts", "integer", "NO", None, None, None),
    ("run_after", "timestamp with time zone", "NO", None, None, None),
    ("lease_owner", "character varying", "YES", 64, None, None),
    ("lease_until", "timestamp with time zone", "YES", None, None, None),
    ("lease_generation", "integer", "NO", None, None, None),
    ("cancel_requested", "boolean", "NO", None, None, None),
    ("progress_stage", "character varying", "NO", 80, None, None),
    ("progress_current", "integer", "NO", None, None, None),
    ("progress_total", "integer", "YES", None, None, None),
    ("safe_error_code", "character varying", "YES", 80, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["jobs"] = (
    ("jobs_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    ("uq_job_idempotency", "UNIQUE", ("unique(idempotency_key)",)),
    (
        "jobs_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "jobs_input_file_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(input_file_id)referencesprivate_files(id)ondelete restrict",),
    ),
)
TABLE_COLUMNS["investment_events"] = (
    ("id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("security_id", "uuid", "YES", None, None, None),
    ("event_type", "character varying", "NO", 24, None, None),
    ("effective_date", "date", "NO", None, None, None),
    ("quantity_delta", "numeric", "YES", None, 28, 10),
    ("cash_amount", "numeric", "YES", None, 28, 10),
    ("currency", "character varying", "NO", 3, None, None),
    ("is_external_flow", "boolean", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("source_event_id", "character varying", "YES", 200, None, None),
    ("evidence_ref", "character varying", "YES", 500, None, None),
    ("quality_status", "character varying", "NO", 24, None, None),
    ("review_status", "character varying", "NO", 24, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("raw_values", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["investment_events"] = (
    ("investment_events_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "ck_investment_event_type",
        "CHECK",
        (
            "event_type",
            "buy",
            "sell",
            "dividend",
            "fee",
            "deposit",
            "withdrawal",
            "transfer_in",
            "transfer_out",
            "split",
            "adjustment",
            "other",
        ),
    ),
    (
        "investment_events_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "investment_events_security_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
    ),
    (
        "uq_investment_event_idempotency",
        "UNIQUE",
        ("unique(idempotency_key)",),
    ),
)
TABLE_COLUMNS["tax_lot_imports"] = (
    ("id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("file_id", "uuid", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("parser_version", "character varying", "NO", 80, None, None),
    ("file_sha256", "character varying", "NO", 64, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("review_revision", "integer", "NO", None, None, None),
    ("row_count", "integer", "NO", None, None, None),
    ("status", "character varying", "NO", 24, None, None),
    ("diagnostics", "jsonb", "NO", None, None, None),
    ("published_at", "timestamp with time zone", "YES", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["tax_lot_imports"] = (
    ("tax_lot_imports_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    ("uq_tax_lot_import_idempotency", "UNIQUE", ("unique(idempotency_key)",)),
    (
        "uq_tax_lot_import_file",
        "UNIQUE",
        ("unique(account_id,source_label,file_sha256)",),
    ),
    (
        "tax_lot_imports_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "tax_lot_imports_file_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(file_id)referencesprivate_files(id)ondelete restrict",),
    ),
)
TABLE_COLUMNS["tax_lot_import_rows"] = (
    ("id", "uuid", "NO", None, None, None),
    ("import_id", "uuid", "NO", None, None, None),
    ("row_number", "integer", "NO", None, None, None),
    ("raw_payload", "jsonb", "NO", None, None, None),
    ("raw_ticker", "character varying", "YES", 200, None, None),
    ("raw_source_lot_id", "character varying", "YES", 200, None, None),
    ("security_id", "uuid", "YES", None, None, None),
    ("acquired_at", "date", "YES", None, None, None),
    ("initial_quantity", "numeric", "YES", None, 28, 10),
    ("remaining_quantity", "numeric", "YES", None, 28, 10),
    ("initial_basis", "numeric", "YES", None, 28, 10),
    ("remaining_basis", "numeric", "YES", None, 28, 10),
    ("basis_currency", "character varying", "YES", 3, None, None),
    ("evidence_ref", "character varying", "YES", 500, None, None),
    ("quality_status", "character varying", "NO", 24, None, None),
    ("row_status", "character varying", "NO", 24, None, None),
    ("diagnostics", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["tax_lot_import_rows"] = (
    ("tax_lot_import_rows_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    ("uq_tax_lot_import_row", "UNIQUE", ("unique(import_id,row_number)",)),
    (
        "tax_lot_import_rows_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_id)referencestax_lot_imports(id)ondelete cascade",),
    ),
    (
        "tax_lot_import_rows_security_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
    ),
)
TABLE_COLUMNS["tax_lots"] = (
    ("id", "uuid", "NO", None, None, None),
    ("account_id", "uuid", "NO", None, None, None),
    ("security_id", "uuid", "NO", None, None, None),
    ("import_id", "uuid", "NO", None, None, None),
    ("import_row_id", "uuid", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("source_lot_id", "character varying", "YES", 200, None, None),
    ("identity_key", "character varying", "NO", 64, None, None),
    ("acquired_at", "date", "YES", None, None, None),
    ("initial_quantity", "numeric", "YES", None, 28, 10),
    ("remaining_quantity", "numeric", "NO", None, 28, 10),
    ("initial_basis", "numeric", "YES", None, 28, 10),
    ("remaining_basis", "numeric", "YES", None, 28, 10),
    ("basis_currency", "character varying", "YES", 3, None, None),
    ("evidence_ref", "character varying", "YES", 500, None, None),
    ("quality_status", "character varying", "NO", 24, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
    ("updated_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["tax_lots"] = (
    ("tax_lots_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "uq_tax_lot_identity",
        "UNIQUE",
        ("unique(account_id,source_label,identity_key)",),
    ),
    ("uq_tax_lots_import_row", "UNIQUE", ("unique(import_row_id)",)),
    (
        "tax_lots_account_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(account_id)referencesaccounts(id)ondelete restrict",),
    ),
    (
        "tax_lots_security_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(security_id)referencessecurities(id)ondelete restrict",),
    ),
    (
        "tax_lots_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_id)referencestax_lot_imports(id)ondelete restrict",),
    ),
    (
        "tax_lots_import_row_id_fkey",
        "FOREIGN KEY",
        (
            "foreignkey(import_row_id)referencestax_lot_import_rows(id)"
            "ondelete restrict",
        ),
    ),
)
TABLE_COLUMNS["tax_lot_adjustments"] = (
    ("id", "uuid", "NO", None, None, None),
    ("tax_lot_id", "uuid", "NO", None, None, None),
    ("adjustment_type", "character varying", "NO", 32, None, None),
    ("quantity_delta", "numeric", "YES", None, 28, 10),
    ("basis_delta", "numeric", "YES", None, 28, 10),
    ("basis_currency", "character varying", "YES", 3, None, None),
    ("effective_date", "date", "NO", None, None, None),
    ("source_label", "character varying", "NO", 100, None, None),
    ("reason", "character varying", "NO", 500, None, None),
    ("evidence_ref", "character varying", "YES", 500, None, None),
    ("idempotency_key", "character varying", "NO", 128, None, None),
    ("raw_values", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["tax_lot_adjustments"] = (
    ("tax_lot_adjustments_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "uq_tax_lot_adjustment_idempotency",
        "UNIQUE",
        ("unique(idempotency_key)",),
    ),
    (
        "tax_lot_adjustments_tax_lot_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(tax_lot_id)referencestax_lots(id)ondelete restrict",),
    ),
)
TABLE_COLUMNS["tax_lot_review_events"] = (
    ("id", "uuid", "NO", None, None, None),
    ("import_id", "uuid", "NO", None, None, None),
    ("import_row_id", "uuid", "YES", None, None, None),
    ("review_revision", "integer", "NO", None, None, None),
    ("action", "character varying", "NO", 32, None, None),
    ("reason", "character varying", "NO", 500, None, None),
    ("change_payload", "jsonb", "NO", None, None, None),
    ("created_at", "timestamp with time zone", "NO", None, None, None),
)
TABLE_CONSTRAINTS["tax_lot_review_events"] = (
    ("tax_lot_review_events_pkey", "PRIMARY KEY", ("primarykey(id)",)),
    (
        "tax_lot_review_events_import_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_id)referencestax_lot_imports(id)ondelete cascade",),
    ),
    (
        "tax_lot_review_events_import_row_id_fkey",
        "FOREIGN KEY",
        ("foreignkey(import_row_id)referencestax_lot_import_rows(id)ondelete cascade",),
    ),
)

STAGE2_TRANSACTIONS = DsqlMigration(
    "0008_stage2_transactions",
    (
        DsqlMigrationStep(
            "create_spending_categories",
            "table",
            """CREATE TABLE spending_categories (
                id uuid NOT NULL,
                slug varchar(80) NOT NULL,
                display_name varchar(120) NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT spending_categories_pkey PRIMARY KEY (id),
                CONSTRAINT uq_spending_category_slug UNIQUE (slug)
            )""",
            "spending_categories",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_transaction_imports",
            "table",
            """CREATE TABLE transaction_imports (
                id uuid NOT NULL,
                file_id uuid NOT NULL,
                account_id uuid NOT NULL,
                source_label varchar(100) NOT NULL,
                parser_version varchar(80) NOT NULL,
                file_sha256 varchar(64) NOT NULL,
                idempotency_key varchar(128) NOT NULL,
                statement_start date,
                statement_end date,
                review_revision integer NOT NULL,
                row_count integer NOT NULL,
                status varchar(24) NOT NULL,
                diagnostics jsonb NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT transaction_imports_pkey PRIMARY KEY (id),
                CONSTRAINT uq_transaction_import_idempotency UNIQUE (idempotency_key),
                CONSTRAINT transaction_imports_file_id_fkey FOREIGN KEY (file_id)
                    REFERENCES private_files(id) ON DELETE RESTRICT,
                CONSTRAINT transaction_imports_account_id_fkey FOREIGN KEY (account_id)
                    REFERENCES accounts(id) ON DELETE RESTRICT
            )""",
            "transaction_imports",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_financial_transactions",
            "table",
            """CREATE TABLE financial_transactions (
                id uuid NOT NULL,
                account_id uuid NOT NULL,
                import_id uuid,
                row_number integer,
                source_label varchar(100) NOT NULL,
                provider_transaction_id varchar(200),
                raw_posted_date varchar(100),
                posted_date date,
                raw_transaction_date varchar(100),
                transaction_date date,
                raw_amount varchar(100),
                amount numeric(24, 10),
                raw_currency varchar(40),
                currency varchar(3),
                raw_description text NOT NULL,
                description text NOT NULL,
                normalized_merchant varchar(200) NOT NULL,
                raw_type varchar(120),
                raw_payload jsonb NOT NULL,
                fingerprint varchar(64) NOT NULL,
                status varchar(24) NOT NULL,
                identity_resolution varchar(24),
                duplicate_of_transaction_id uuid,
                classification varchar(24) NOT NULL,
                category_id uuid,
                category_source varchar(24) NOT NULL,
                revision integer NOT NULL,
                idempotency_key varchar(128),
                diagnostics jsonb NOT NULL,
                published_at timestamptz,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT financial_transactions_pkey PRIMARY KEY (id),
                CONSTRAINT uq_transaction_import_row UNIQUE (import_id, row_number),
                CONSTRAINT financial_transactions_idempotency_key_key
                    UNIQUE (idempotency_key),
                CONSTRAINT financial_transactions_account_id_fkey
                    FOREIGN KEY (account_id)
                    REFERENCES accounts(id) ON DELETE RESTRICT,
                CONSTRAINT financial_transactions_import_id_fkey FOREIGN KEY (import_id)
                    REFERENCES transaction_imports(id) ON DELETE RESTRICT,
                CONSTRAINT financial_transactions_category_id_fkey
                    FOREIGN KEY (category_id)
                    REFERENCES spending_categories(id) ON DELETE SET NULL,
                CONSTRAINT financial_transactions_duplicate_of_transaction_id_fkey
                    FOREIGN KEY (duplicate_of_transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE SET NULL
            )""",
            "financial_transactions",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_transaction_provider_identities",
            "table",
            """CREATE TABLE transaction_provider_identities (
                id uuid NOT NULL,
                account_id uuid NOT NULL,
                source_label varchar(100) NOT NULL,
                provider_transaction_id varchar(200) NOT NULL,
                transaction_id uuid NOT NULL,
                CONSTRAINT transaction_provider_identities_pkey PRIMARY KEY (id),
                CONSTRAINT uq_transaction_provider_identity UNIQUE
                    (account_id, source_label, provider_transaction_id),
                CONSTRAINT uq_transaction_provider_transaction UNIQUE (transaction_id),
                CONSTRAINT transaction_provider_identities_account_id_fkey
                    FOREIGN KEY (account_id)
                    REFERENCES accounts(id) ON DELETE RESTRICT,
                CONSTRAINT transaction_provider_identities_transaction_id_fkey
                    FOREIGN KEY (transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE CASCADE
            )""",
            "transaction_provider_identities",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_merchant_category_rules",
            "table",
            """CREATE TABLE merchant_category_rules (
                id uuid NOT NULL,
                normalized_merchant varchar(200) NOT NULL,
                category_id uuid NOT NULL,
                priority integer NOT NULL,
                version integer NOT NULL,
                active boolean NOT NULL,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT merchant_category_rules_pkey PRIMARY KEY (id),
                CONSTRAINT uq_merchant_category_rule_version
                    UNIQUE (normalized_merchant, version),
                CONSTRAINT merchant_category_rules_category_id_fkey
                    FOREIGN KEY (category_id)
                    REFERENCES spending_categories(id) ON DELETE RESTRICT
            )""",
            "merchant_category_rules",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_transaction_review_events",
            "table",
            """CREATE TABLE transaction_review_events (
                id uuid NOT NULL,
                transaction_id uuid NOT NULL,
                import_id uuid,
                review_revision integer NOT NULL,
                action varchar(32) NOT NULL,
                reason varchar(500) NOT NULL,
                change_payload jsonb NOT NULL,
                created_at timestamptz NOT NULL,
                CONSTRAINT transaction_review_events_pkey PRIMARY KEY (id),
                CONSTRAINT transaction_review_events_transaction_id_fkey
                    FOREIGN KEY (transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE CASCADE,
                CONSTRAINT transaction_review_events_import_id_fkey
                    FOREIGN KEY (import_id)
                    REFERENCES transaction_imports(id) ON DELETE CASCADE
            )""",
            "transaction_review_events",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_transaction_splits",
            "table",
            """CREATE TABLE transaction_splits (
                id uuid NOT NULL,
                transaction_id uuid NOT NULL,
                split_index integer NOT NULL,
                amount numeric(24, 10) NOT NULL,
                category_id uuid,
                note varchar(500),
                revision integer NOT NULL,
                CONSTRAINT transaction_splits_pkey PRIMARY KEY (id),
                CONSTRAINT uq_transaction_split_index
                    UNIQUE (transaction_id, split_index),
                CONSTRAINT transaction_splits_transaction_id_fkey
                    FOREIGN KEY (transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE CASCADE,
                CONSTRAINT transaction_splits_category_id_fkey FOREIGN KEY (category_id)
                    REFERENCES spending_categories(id) ON DELETE SET NULL
            )""",
            "transaction_splits",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_transfer_matches",
            "table",
            """CREATE TABLE transfer_matches (
                id uuid NOT NULL,
                first_transaction_id uuid NOT NULL,
                second_transaction_id uuid NOT NULL,
                status varchar(24) NOT NULL,
                match_method varchar(32) NOT NULL,
                reason varchar(500) NOT NULL,
                confirmed_at timestamptz,
                created_at timestamptz NOT NULL,
                updated_at timestamptz NOT NULL,
                CONSTRAINT transfer_matches_pkey PRIMARY KEY (id),
                CONSTRAINT transfer_matches_first_transaction_id_fkey
                    FOREIGN KEY (first_transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE RESTRICT,
                CONSTRAINT transfer_matches_second_transaction_id_fkey
                    FOREIGN KEY (second_transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE RESTRICT
            )""",
            "transfer_matches",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "create_active_transfer_transactions",
            "table",
            """CREATE TABLE active_transfer_transactions (
                transaction_id uuid NOT NULL,
                transfer_id uuid NOT NULL,
                CONSTRAINT active_transfer_transactions_pkey
                    PRIMARY KEY (transaction_id),
                CONSTRAINT active_transfer_transactions_transaction_id_fkey
                    FOREIGN KEY (transaction_id)
                    REFERENCES financial_transactions(id) ON DELETE RESTRICT,
                CONSTRAINT active_transfer_transactions_transfer_id_fkey
                    FOREIGN KEY (transfer_id)
                    REFERENCES transfer_matches(id) ON DELETE CASCADE
            )""",
            "active_transfer_transactions",
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :object_name)",
        ),
        DsqlMigrationStep(
            "index_transaction_imports_account",
            "index",
            "CREATE INDEX ASYNC ix_transaction_imports_account "
            "ON transaction_imports (account_id, created_at)",
            "ix_transaction_imports_account",
            "SELECT true",
            expected_index_table="transaction_imports",
            expected_index_columns=("account_id", "created_at"),
        ),
        DsqlMigrationStep(
            "index_transactions_account_posted",
            "index",
            "CREATE INDEX ASYNC ix_transactions_account_posted "
            "ON financial_transactions (account_id, posted_date)",
            "ix_transactions_account_posted",
            "SELECT true",
            expected_index_table="financial_transactions",
            expected_index_columns=("account_id", "posted_date"),
        ),
        DsqlMigrationStep(
            "index_transactions_import_status",
            "index",
            "CREATE INDEX ASYNC ix_transactions_import_status "
            "ON financial_transactions (import_id, status)",
            "ix_transactions_import_status",
            "SELECT true",
            expected_index_table="financial_transactions",
            expected_index_columns=("import_id", "status"),
        ),
        DsqlMigrationStep(
            "index_merchant_category_rule_lookup",
            "index",
            "CREATE INDEX ASYNC ix_merchant_category_rule_lookup "
            "ON merchant_category_rules (normalized_merchant, active)",
            "ix_merchant_category_rule_lookup",
            "SELECT true",
            expected_index_table="merchant_category_rules",
            expected_index_columns=("normalized_merchant", "active"),
        ),
        DsqlMigrationStep(
            "index_transaction_events_transaction",
            "index",
            "CREATE INDEX ASYNC ix_transaction_events_transaction "
            "ON transaction_review_events (transaction_id, created_at)",
            "ix_transaction_events_transaction",
            "SELECT true",
            expected_index_table="transaction_review_events",
            expected_index_columns=("transaction_id", "created_at"),
        ),
        DsqlMigrationStep(
            "index_transaction_splits_transaction",
            "index",
            "CREATE INDEX ASYNC ix_transaction_splits_transaction "
            "ON transaction_splits (transaction_id)",
            "ix_transaction_splits_transaction",
            "SELECT true",
            expected_index_table="transaction_splits",
            expected_index_columns=("transaction_id",),
        ),
        DsqlMigrationStep(
            "index_active_transfer_transactions_transfer",
            "index",
            "CREATE INDEX ASYNC ix_active_transfer_transactions_transfer "
            "ON active_transfer_transactions (transfer_id)",
            "ix_active_transfer_transactions_transfer",
            "SELECT true",
            expected_index_table="active_transfer_transactions",
            expected_index_columns=("transfer_id",),
        ),
    ),
)

DSQL_MIGRATIONS = (
    CORE_SCHEMA,
    POSITION_SNAPSHOT_REVISION,
    IMMUTABLE_POSITION_REVISIONS_AND_IDENTIFIERS,
    STAGE1_POSITION_IMPORTS,
    STAGE1_FUND_COMPOSITIONS,
    STAGE1_REPORTS,
    STAGE2_DOCUMENT_INGESTION,
    STAGE2_TRANSACTIONS,
    DsqlMigration(
        "0009_stage2_finance_balances",
        (
            DsqlMigrationStep(
                "create_account_balance_observations",
                "table",
                """CREATE TABLE account_balance_observations (
                    id uuid NOT NULL,
                    account_id uuid NOT NULL,
                    as_of date NOT NULL,
                    revision integer NOT NULL,
                    balance_kind varchar(12) NOT NULL,
                    amount numeric(24, 10) NOT NULL,
                    currency varchar(3) NOT NULL,
                    source varchar(100) NOT NULL,
                    quality_status varchar(24) NOT NULL,
                    idempotency_key varchar(128) NOT NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    CONSTRAINT account_balance_observations_pkey PRIMARY KEY (id),
                    CONSTRAINT ck_account_balance_nonnegative CHECK (amount >= 0),
                    CONSTRAINT uq_account_balance_revision
                        UNIQUE (account_id, as_of, revision),
                    CONSTRAINT uq_account_balance_idempotency UNIQUE (idempotency_key),
                    CONSTRAINT account_balance_observations_account_id_fkey
                        FOREIGN KEY (account_id) REFERENCES accounts(id)
                        ON DELETE RESTRICT
                )""",
                "account_balance_observations",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_account_balances_account_date",
                "index",
                "CREATE INDEX ASYNC ix_account_balances_account_date "
                "ON account_balance_observations (account_id, as_of)",
                "ix_account_balances_account_date",
                "SELECT true",
                expected_index_table="account_balance_observations",
                expected_index_columns=("account_id", "as_of"),
            ),
        ),
    ),
    DsqlMigration(
        "0010_stage2_durable_jobs",
        (
            DsqlMigrationStep(
                "create_jobs",
                "table",
                """CREATE TABLE jobs (
                    id uuid NOT NULL,
                    job_type varchar(64) NOT NULL,
                    account_id uuid,
                    input_file_id uuid,
                    idempotency_key varchar(128) NOT NULL,
                    payload jsonb NOT NULL,
                    result jsonb,
                    status varchar(24) NOT NULL,
                    attempts integer NOT NULL,
                    max_attempts integer NOT NULL,
                    run_after timestamptz NOT NULL,
                    lease_owner varchar(64),
                    lease_until timestamptz,
                    lease_generation integer NOT NULL,
                    cancel_requested boolean NOT NULL,
                    progress_stage varchar(80) NOT NULL,
                    progress_current integer NOT NULL,
                    progress_total integer,
                    safe_error_code varchar(80),
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    CONSTRAINT jobs_pkey PRIMARY KEY (id),
                    CONSTRAINT uq_job_idempotency UNIQUE (idempotency_key),
                    CONSTRAINT jobs_account_id_fkey FOREIGN KEY (account_id)
                        REFERENCES accounts(id) ON DELETE RESTRICT,
                    CONSTRAINT jobs_input_file_id_fkey FOREIGN KEY (input_file_id)
                        REFERENCES private_files(id) ON DELETE RESTRICT
                )""",
                "jobs",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_jobs_claim",
                "index",
                "CREATE INDEX ASYNC ix_jobs_claim "
                "ON jobs (status, run_after, created_at)",
                "ix_jobs_claim",
                "SELECT true",
                expected_index_table="jobs",
                expected_index_columns=("status", "run_after", "created_at"),
            ),
        ),
    ),
    DsqlMigration(
        "0012_stage3_investment_events",
        (
            DsqlMigrationStep(
                "create_investment_events",
                "table",
                """CREATE TABLE investment_events (
                    id uuid NOT NULL,
                    account_id uuid NOT NULL,
                    security_id uuid,
                    event_type varchar(24) NOT NULL,
                    effective_date date NOT NULL,
                    quantity_delta numeric(28, 10),
                    cash_amount numeric(28, 10),
                    currency varchar(3) NOT NULL,
                    is_external_flow boolean NOT NULL,
                    source_label varchar(100) NOT NULL,
                    source_event_id varchar(200),
                    evidence_ref varchar(500),
                    quality_status varchar(24) NOT NULL,
                    review_status varchar(24) NOT NULL,
                    idempotency_key varchar(128) NOT NULL,
                    raw_values jsonb NOT NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    CONSTRAINT investment_events_pkey PRIMARY KEY (id),
                    CONSTRAINT ck_investment_event_type CHECK
                        (event_type IN ('buy', 'sell', 'dividend', 'fee', 'deposit',
                        'withdrawal', 'transfer_in', 'transfer_out', 'split',
                        'adjustment', 'other')),
                    CONSTRAINT investment_events_account_id_fkey FOREIGN KEY
                        (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
                    CONSTRAINT investment_events_security_id_fkey FOREIGN KEY
                        (security_id) REFERENCES securities(id) ON DELETE RESTRICT,
                    CONSTRAINT uq_investment_event_idempotency
                        UNIQUE (idempotency_key)
                )""",
                "investment_events",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_investment_events_account_date",
                "index",
                "CREATE INDEX ASYNC ix_investment_events_account_date "
                "ON investment_events (account_id, effective_date)",
                "ix_investment_events_account_date",
                "SELECT true",
                expected_index_table="investment_events",
                expected_index_columns=("account_id", "effective_date"),
            ),
            DsqlMigrationStep(
                "index_investment_events_security_date",
                "index",
                "CREATE INDEX ASYNC ix_investment_events_security_date "
                "ON investment_events (security_id, effective_date)",
                "ix_investment_events_security_date",
                "SELECT true",
                expected_index_table="investment_events",
                expected_index_columns=("security_id", "effective_date"),
            ),
        ),
    ),
    DsqlMigration(
        "0013_stage3_tax_lots",
        (
            DsqlMigrationStep(
                "create_tax_lot_imports",
                "table",
                """CREATE TABLE tax_lot_imports (
                    id uuid NOT NULL,
                    account_id uuid NOT NULL,
                    file_id uuid NOT NULL,
                    source_label varchar(100) NOT NULL,
                    parser_version varchar(80) NOT NULL,
                    file_sha256 varchar(64) NOT NULL,
                    idempotency_key varchar(128) NOT NULL,
                    review_revision integer NOT NULL,
                    row_count integer NOT NULL,
                    status varchar(24) NOT NULL,
                    diagnostics jsonb NOT NULL,
                    published_at timestamptz,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    CONSTRAINT tax_lot_imports_pkey PRIMARY KEY (id),
                    CONSTRAINT uq_tax_lot_import_idempotency UNIQUE (idempotency_key),
                    CONSTRAINT uq_tax_lot_import_file
                        UNIQUE (account_id, source_label, file_sha256),
                    CONSTRAINT tax_lot_imports_account_id_fkey FOREIGN KEY (account_id)
                        REFERENCES accounts(id) ON DELETE RESTRICT,
                    CONSTRAINT tax_lot_imports_file_id_fkey FOREIGN KEY (file_id)
                        REFERENCES private_files(id) ON DELETE RESTRICT
                )""",
                "tax_lot_imports",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_tax_lot_imports_account_created",
                "index",
                "CREATE INDEX ASYNC ix_tax_lot_imports_account_created "
                "ON tax_lot_imports (account_id, created_at)",
                "ix_tax_lot_imports_account_created",
                "SELECT true",
                expected_index_table="tax_lot_imports",
                expected_index_columns=("account_id", "created_at"),
            ),
            DsqlMigrationStep(
                "create_tax_lot_import_rows",
                "table",
                """CREATE TABLE tax_lot_import_rows (
                    id uuid NOT NULL,
                    import_id uuid NOT NULL,
                    row_number integer NOT NULL,
                    raw_payload jsonb NOT NULL,
                    raw_ticker varchar(200),
                    raw_source_lot_id varchar(200),
                    security_id uuid,
                    acquired_at date,
                    initial_quantity numeric(28, 10),
                    remaining_quantity numeric(28, 10),
                    initial_basis numeric(28, 10),
                    remaining_basis numeric(28, 10),
                    basis_currency varchar(3),
                    evidence_ref varchar(500),
                    quality_status varchar(24) NOT NULL,
                    row_status varchar(24) NOT NULL,
                    diagnostics jsonb NOT NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    CONSTRAINT tax_lot_import_rows_pkey PRIMARY KEY (id),
                    CONSTRAINT uq_tax_lot_import_row UNIQUE (import_id, row_number),
                    CONSTRAINT tax_lot_import_rows_import_id_fkey FOREIGN KEY
                        (import_id)
                        REFERENCES tax_lot_imports(id) ON DELETE CASCADE,
                    CONSTRAINT tax_lot_import_rows_security_id_fkey FOREIGN KEY
                        (security_id) REFERENCES securities(id) ON DELETE RESTRICT
                )""",
                "tax_lot_import_rows",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_tax_lot_import_rows_import",
                "index",
                "CREATE INDEX ASYNC ix_tax_lot_import_rows_import "
                "ON tax_lot_import_rows (import_id, row_number)",
                "ix_tax_lot_import_rows_import",
                "SELECT true",
                expected_index_table="tax_lot_import_rows",
                expected_index_columns=("import_id", "row_number"),
            ),
            DsqlMigrationStep(
                "create_tax_lots",
                "table",
                """CREATE TABLE tax_lots (
                    id uuid NOT NULL,
                    account_id uuid NOT NULL,
                    security_id uuid NOT NULL,
                    import_id uuid NOT NULL,
                    import_row_id uuid NOT NULL,
                    source_label varchar(100) NOT NULL,
                    source_lot_id varchar(200),
                    identity_key varchar(64) NOT NULL,
                    acquired_at date,
                    initial_quantity numeric(28, 10),
                    remaining_quantity numeric(28, 10) NOT NULL,
                    initial_basis numeric(28, 10),
                    remaining_basis numeric(28, 10),
                    basis_currency varchar(3),
                    evidence_ref varchar(500),
                    quality_status varchar(24) NOT NULL,
                    created_at timestamptz NOT NULL,
                    updated_at timestamptz NOT NULL,
                    CONSTRAINT tax_lots_pkey PRIMARY KEY (id),
                    CONSTRAINT uq_tax_lot_identity UNIQUE
                        (account_id, source_label, identity_key),
                    CONSTRAINT uq_tax_lots_import_row UNIQUE (import_row_id),
                    CONSTRAINT tax_lots_account_id_fkey FOREIGN KEY (account_id)
                        REFERENCES accounts(id) ON DELETE RESTRICT,
                    CONSTRAINT tax_lots_security_id_fkey FOREIGN KEY (security_id)
                        REFERENCES securities(id) ON DELETE RESTRICT,
                    CONSTRAINT tax_lots_import_id_fkey FOREIGN KEY (import_id)
                        REFERENCES tax_lot_imports(id) ON DELETE RESTRICT,
                    CONSTRAINT tax_lots_import_row_id_fkey FOREIGN KEY (import_row_id)
                        REFERENCES tax_lot_import_rows(id) ON DELETE RESTRICT
                )""",
                "tax_lots",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_tax_lots_account_security",
                "index",
                "CREATE INDEX ASYNC ix_tax_lots_account_security "
                "ON tax_lots (account_id, security_id)",
                "ix_tax_lots_account_security",
                "SELECT true",
                expected_index_table="tax_lots",
                expected_index_columns=("account_id", "security_id"),
            ),
            DsqlMigrationStep(
                "index_tax_lots_security_acquired",
                "index",
                "CREATE INDEX ASYNC ix_tax_lots_security_acquired "
                "ON tax_lots (security_id, acquired_at)",
                "ix_tax_lots_security_acquired",
                "SELECT true",
                expected_index_table="tax_lots",
                expected_index_columns=("security_id", "acquired_at"),
            ),
            DsqlMigrationStep(
                "create_tax_lot_adjustments",
                "table",
                """CREATE TABLE tax_lot_adjustments (
                    id uuid NOT NULL,
                    tax_lot_id uuid NOT NULL,
                    adjustment_type varchar(32) NOT NULL,
                    quantity_delta numeric(28, 10),
                    basis_delta numeric(28, 10),
                    basis_currency varchar(3),
                    effective_date date NOT NULL,
                    source_label varchar(100) NOT NULL,
                    reason varchar(500) NOT NULL,
                    evidence_ref varchar(500),
                    idempotency_key varchar(128) NOT NULL,
                    raw_values jsonb NOT NULL,
                    created_at timestamptz NOT NULL,
                    CONSTRAINT tax_lot_adjustments_pkey PRIMARY KEY (id),
                    CONSTRAINT uq_tax_lot_adjustment_idempotency UNIQUE
                        (idempotency_key),
                    CONSTRAINT tax_lot_adjustments_tax_lot_id_fkey FOREIGN KEY
                        (tax_lot_id) REFERENCES tax_lots(id) ON DELETE RESTRICT
                )""",
                "tax_lot_adjustments",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_tax_lot_adjustments_lot_date",
                "index",
                "CREATE INDEX ASYNC ix_tax_lot_adjustments_lot_date "
                "ON tax_lot_adjustments (tax_lot_id, effective_date)",
                "ix_tax_lot_adjustments_lot_date",
                "SELECT true",
                expected_index_table="tax_lot_adjustments",
                expected_index_columns=("tax_lot_id", "effective_date"),
            ),
            DsqlMigrationStep(
                "create_tax_lot_review_events",
                "table",
                """CREATE TABLE tax_lot_review_events (
                    id uuid NOT NULL,
                    import_id uuid NOT NULL,
                    import_row_id uuid,
                    review_revision integer NOT NULL,
                    action varchar(32) NOT NULL,
                    reason varchar(500) NOT NULL,
                    change_payload jsonb NOT NULL,
                    created_at timestamptz NOT NULL,
                    CONSTRAINT tax_lot_review_events_pkey PRIMARY KEY (id),
                    CONSTRAINT tax_lot_review_events_import_id_fkey FOREIGN KEY
                        (import_id) REFERENCES tax_lot_imports(id) ON DELETE CASCADE,
                    CONSTRAINT tax_lot_review_events_import_row_id_fkey FOREIGN KEY
                        (import_row_id) REFERENCES tax_lot_import_rows(id)
                        ON DELETE CASCADE
                )""",
                "tax_lot_review_events",
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
            ),
            DsqlMigrationStep(
                "index_tax_lot_review_events_import",
                "index",
                "CREATE INDEX ASYNC ix_tax_lot_review_events_import "
                "ON tax_lot_review_events (import_id, created_at)",
                "ix_tax_lot_review_events_import",
                "SELECT true",
                expected_index_table="tax_lot_review_events",
                expected_index_columns=("import_id", "created_at"),
            ),
        ),
    ),
)
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
                ("CREATE INDEX ASYNC", "CREATE UNIQUE INDEX ASYNC")
            ):
                raise MigrationPlanError(
                    f"{step.key} is not an asynchronous index step"
                )
            if step.kind == "alter" and not step.statement.lstrip().upper().startswith(
                "ALTER TABLE"
            ):
                raise MigrationPlanError(f"{step.key} is not an ALTER TABLE step")
            if step.kind in {
                "drop_constraint",
                "add_constraint",
                "async_alter",
            } and not step.statement.lstrip().upper().startswith("ALTER TABLE"):
                raise MigrationPlanError(f"{step.key} is not an ALTER TABLE step")
            if step.kind == "index" and not step.expected_index_table:
                raise MigrationPlanError(f"{step.key} has no expected index table")
            if step.kind == "index" and not step.expected_index_columns:
                raise MigrationPlanError(f"{step.key} has no expected index columns")
            if step.kind != "backfill" and not step.ready_check:
                raise MigrationPlanError(f"{step.key} has no completion check")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _table_matches(engine: Engine, step: DsqlMigrationStep) -> bool:
    table_name = step.object_name
    base_columns = TABLE_COLUMNS.get(table_name)
    base_constraints = TABLE_CONSTRAINTS.get(table_name)
    if base_columns is None or base_constraints is None:
        return bool(_scalar(engine, step.ready_check, object_name=table_name))

    evolved_columns, evolved_constraints, dropped_constraints = TABLE_EVOLUTIONS.get(
        table_name, ((), (), frozenset())
    )
    columns = [(column, True) for column in base_columns] + [
        (column, False) for column in evolved_columns
    ]
    constraints = [
        (constraint, constraint[0] not in dropped_constraints)
        for constraint in base_constraints
    ] + [(constraint, False) for constraint in evolved_constraints]

    column_values = ", ".join(
        "("
        + ", ".join(
            (
                _sql_literal(name),
                _sql_literal(data_type),
                _sql_literal(nullable),
                f"{char_length}::integer"
                if char_length is not None
                else "NULL::integer",
                f"{numeric_precision}::integer"
                if numeric_precision is not None
                else "NULL::integer",
                f"{numeric_scale}::integer"
                if numeric_scale is not None
                else "NULL::integer",
                "TRUE" if required else "FALSE",
            )
        )
        + ")"
        for (
            name,
            data_type,
            nullable,
            char_length,
            numeric_precision,
            numeric_scale,
        ), required in columns
    )
    constraint_matches: list[str] = []
    constraint_values: list[str] = []
    for (name, constraint_type, tokens), required in constraints:
        constraint_values.append(
            "("
            + ", ".join(
                (
                    _sql_literal(name),
                    _sql_literal(constraint_type),
                    "TRUE" if required else "FALSE",
                )
            )
            + ")"
        )
        token_checks = (
            " AND ".join(
                "position("
                + _sql_literal(token.replace(" ", "").lower())
                + " in lower(replace(replace(replace("
                "pg_catalog.pg_get_constraintdef(pc.oid), ' ', ''), '\"', ''), "
                "'public.', ''))) > 0"
                for token in tokens
            )
            or "TRUE"
        )
        constraint_matches.append(
            "(tc.constraint_name = "
            + _sql_literal(name)
            + " AND tc.constraint_type = "
            + _sql_literal(constraint_type)
            + " AND pc.oid IS NOT NULL AND ("
            + token_checks
            + "))"
        )
    constraint_match_clause = " OR ".join(constraint_matches) or "FALSE"
    statement = f"""WITH expected_columns(column_name, data_type, is_nullable,
        character_maximum_length, numeric_precision, numeric_scale, is_required) AS
        (VALUES {column_values})
        , expected_constraints(constraint_name, constraint_type, is_required) AS
        (VALUES {", ".join(constraint_values)})
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables t
          WHERE t.table_schema = current_schema() AND t.table_name = :object_name
            AND NOT EXISTS (
              SELECT 1 FROM expected_columns e
              LEFT JOIN information_schema.columns c
                ON c.table_schema = current_schema() AND c.table_name = :object_name
               AND c.column_name = e.column_name
              WHERE (c.column_name IS NULL AND e.is_required)
                 OR (c.column_name IS NOT NULL AND (
                     c.data_type <> e.data_type
                     OR c.is_nullable <> e.is_nullable
                     OR (e.character_maximum_length IS NOT NULL
                         AND c.character_maximum_length <> e.character_maximum_length)
                     OR (e.numeric_precision IS NOT NULL
                         AND c.numeric_precision <> e.numeric_precision)
                     OR (
                         e.numeric_scale IS NOT NULL
                         AND c.numeric_scale <> e.numeric_scale
                     )
                 ))
            )
            AND NOT EXISTS (
              SELECT 1 FROM information_schema.columns c
              LEFT JOIN expected_columns e ON e.column_name = c.column_name
              WHERE c.table_schema = current_schema() AND c.table_name = :object_name
                AND e.column_name IS NULL
            )
            AND NOT EXISTS (
              SELECT 1 FROM expected_constraints e
              LEFT JOIN information_schema.table_constraints tc
                ON tc.table_schema = current_schema() AND tc.table_name = :object_name
               AND tc.constraint_name = e.constraint_name
              WHERE e.is_required AND tc.constraint_name IS NULL
            )
            AND NOT EXISTS (
              SELECT 1 FROM information_schema.table_constraints tc
              LEFT JOIN pg_catalog.pg_constraint pc
                ON pc.conname = tc.constraint_name
               AND pc.conrelid = (SELECT c.oid FROM pg_catalog.pg_class c
                                  JOIN pg_catalog.pg_namespace n
                                    ON n.oid = c.relnamespace
                                  WHERE n.nspname = current_schema()
                                    AND c.relname = :object_name)
              WHERE tc.table_schema = current_schema() AND tc.table_name = :object_name
                AND NOT ({constraint_match_clause})
            )
            AND NOT EXISTS (
              SELECT 1 FROM information_schema.table_constraints tc
              LEFT JOIN expected_constraints e ON e.constraint_name = tc.constraint_name
              WHERE tc.table_schema = current_schema() AND tc.table_name = :object_name
                AND e.constraint_name IS NULL
            )
        )"""
    return bool(_scalar(engine, statement, object_name=table_name))


def _object_exists(engine: Engine, step: DsqlMigrationStep) -> bool:
    if step.kind == "table":
        return bool(
            _scalar(
                engine,
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_name = :object_name)",
                object_name=step.object_name,
            )
        )
    if step.kind == "index":
        return _index_exists(engine, step.object_name)
    if step.kind == "alter" and "." in step.object_name:
        table_name, column_name = step.object_name.split(".", 1)
        return bool(
            _scalar(
                engine,
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :table_name "
                "AND column_name = :column_name)",
                table_name=table_name,
                column_name=column_name,
            )
        )
    if (
        step.kind in {"drop_constraint", "add_constraint", "async_alter"}
        and step.expected_constraint
    ):
        table_name, constraint_name, _constraint_type, _tokens = (
            step.expected_constraint
        )
        return _constraint_exists(engine, table_name, constraint_name)
    return False


def _column_matches(engine: Engine, step: DsqlMigrationStep) -> bool:
    if step.expected_column is None:
        return bool(_scalar(engine, step.ready_check, object_name=step.object_name))
    table_name, column_name = step.object_name.split(".", 1)
    data_type, nullable, default = step.expected_column
    default_clause = (
        " AND column_default LIKE :column_default"
        if default is not None and "%" in default
        else " AND column_default = :column_default"
        if default is not None
        else " AND column_default IS NULL"
    )
    return bool(
        _scalar(
            engine,
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :table_name "
            "AND column_name = :column_name AND data_type = :data_type "
            "AND is_nullable = :is_nullable" + default_clause + ")",
            table_name=table_name,
            column_name=column_name,
            data_type=data_type,
            is_nullable=nullable,
            **({"column_default": default} if default is not None else {}),
        )
    )


def _constraint_exists(engine: Engine, table_name: str, constraint_name: str) -> bool:
    return bool(
        _scalar(
            engine,
            "SELECT EXISTS (SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = current_schema() AND table_name = :table_name "
            "AND constraint_name = :constraint_name)",
            table_name=table_name,
            constraint_name=constraint_name,
        )
    )


def _constraint_matches(
    engine: Engine,
    expected: tuple[str, str, str, tuple[str, ...]],
    *,
    validated: bool | None,
) -> bool:
    table_name, constraint_name, constraint_type, tokens = expected
    definition_checks = (
        " AND ".join(
            "position("
            + _sql_literal(token.replace(" ", "").lower())
            + " in lower(replace(replace(replace("
            "pg_catalog.pg_get_constraintdef(pc.oid), "
            "' ', ''), '\"', ''), 'public.', ''))) > 0"
            for token in tokens
        )
        or "TRUE"
    )
    validated_clause = "" if validated is None else " AND pc.convalidated = :validated"
    return bool(
        _scalar(
            engine,
            "SELECT EXISTS (SELECT 1 FROM information_schema.table_constraints tc "
            "JOIN pg_catalog.pg_constraint pc ON pc.conname = tc.constraint_name "
            "JOIN pg_catalog.pg_class c ON c.oid = pc.conrelid "
            "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
            "WHERE tc.table_schema = current_schema() AND tc.table_name = :table_name "
            "AND tc.constraint_name = :constraint_name "
            "AND tc.constraint_type = :constraint_type "
            "AND n.nspname = current_schema() AND c.relname = :table_name "
            "AND (" + definition_checks + ")" + validated_clause + ")",
            table_name=table_name,
            constraint_name=constraint_name,
            constraint_type=constraint_type,
            **({"validated": validated} if validated is not None else {}),
        )
    )


def _index_definition_matches(
    engine: Engine, step: DsqlMigrationStep, *, require_valid: bool
) -> bool:
    index_table = step.expected_index_table
    if index_table is None:
        return False
    definition = _scalar(
        engine,
        "SELECT pg_catalog.pg_get_indexdef(c.oid) "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid "
        "JOIN pg_catalog.pg_class t ON t.oid = i.indrelid "
        "WHERE n.nspname = current_schema() AND c.relname = :object_name "
        "AND t.relname = :table_name AND i.indnkeyatts = :key_count "
        "AND i.indpred IS NULL AND i.indexprs IS NULL "
        "AND i.indisunique = :is_unique"
        + (" AND i.indisvalid" if require_valid else ""),
        object_name=step.object_name,
        table_name=step.expected_index_table,
        key_count=len(step.expected_index_columns),
        is_unique=step.expected_index_unique,
    )
    if not isinstance(definition, str):
        return False
    normalized = "".join(
        definition.lower().replace('"', "").replace("public.", "").split()
    )
    columns = "(" + ",".join(step.expected_index_columns).lower() + ")"
    expected_kind = "createuniqueindex" if step.expected_index_unique else "createindex"
    return (
        normalized.startswith(expected_kind)
        and f"on{index_table.lower()}usingbtree" in normalized
        and normalized.endswith(columns)
        and "where" not in normalized
        and "include" not in normalized
    )


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
            raise RuntimeError(f"Aurora DSQL asynchronous DDL job {job_id} failed")


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
    if _index_definition_matches(engine, step, require_valid=True):
        return True
    if not _index_exists(engine, step.object_name):
        return False
    if not _index_definition_matches(engine, step, require_valid=False):
        raise MigrationPlanError(
            f"Aurora DSQL index definition drift at {step.object_name}; "
            "an existing index has incompatible table, key, uniqueness or predicate."
        )
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
        if _index_definition_matches(engine, step, require_valid=True):
            return True
    # DSQL leaves a failed async index INVALID. Remove this plan-owned index
    # in its own DDL transaction so a later execution can safely recreate it.
    _execute_one(engine, f"DROP INDEX IF EXISTS {step.object_name}")
    return False


def _is_complete(engine: Engine, step: DsqlMigrationStep) -> bool:
    if step.kind == "index":
        return _resume_index(engine, step)
    if step.kind == "table":
        if not _object_exists(engine, step):
            return False
        if not _table_matches(engine, step):
            raise MigrationPlanError(
                f"Aurora DSQL table definition drift at {step.object_name}; "
                "existing columns or constraints do not match this migration."
            )
        return True
    if step.kind == "alter":
        if not _object_exists(engine, step):
            return False
        if not _column_matches(engine, step):
            raise MigrationPlanError(
                f"Aurora DSQL column definition drift at {step.object_name}; "
                "existing type, nullability or default does not match this migration."
            )
        return True
    if step.kind == "drop_constraint":
        if step.expected_constraint is None:
            raise MigrationPlanError(f"{step.key} has no expected dropped constraint")
        if not _constraint_exists(
            engine, step.expected_constraint[0], step.expected_constraint[1]
        ):
            return True
        if not _constraint_matches(engine, step.expected_constraint, validated=None):
            raise MigrationPlanError(
                f"Aurora DSQL constraint definition drift at {step.object_name}; "
                "refusing to drop an incompatible constraint."
            )
        return False
    if step.kind in {"add_constraint", "async_alter"}:
        if step.expected_constraint is None:
            raise MigrationPlanError(f"{step.key} has no expected constraint")
        if not _constraint_exists(
            engine, step.expected_constraint[0], step.expected_constraint[1]
        ):
            return False
        if not _constraint_matches(
            engine,
            step.expected_constraint,
            validated=step.expected_constraint_validated,
        ):
            # A NOT VALID constraint is an expected intermediate state for its
            # ADD step. Once the later asynchronous validation step completes,
            # the prior ADD step remains complete as well.
            if step.expected_constraint_validated is False and _constraint_matches(
                engine, step.expected_constraint, validated=True
            ):
                return True
            if not _constraint_matches(
                engine, step.expected_constraint, validated=None
            ):
                raise MigrationPlanError(
                    f"Aurora DSQL constraint definition drift at {step.object_name}"
                )
            return False
        return True
    return False


def _fetch_rows(
    engine: Engine, statement: str, **parameters: object
) -> list[dict[str, object]]:
    with engine.connect() as connection:
        return [
            dict(row._mapping)
            for row in connection.execute(text(statement), parameters).all()
        ]


def _backfill_manual_revisions(engine: Engine, batch_size: int = 100) -> None:
    """Idempotently reconcile legacy manual revisions in bounded DML units."""
    if batch_size < 1 or batch_size > 500:
        raise ValueError("DSQL revision backfill batch_size must be from 1 to 500")
    accounts = _fetch_rows(engine, "SELECT id FROM accounts ORDER BY id")
    for account_row in accounts:
        account_id = account_row["id"]
        rows = _fetch_rows(
            engine,
            "SELECT id, source, status, created_at FROM position_snapshots "
            "WHERE account_id = :account_id ORDER BY source, created_at, id",
            account_id=account_id,
        )
        selected_id = _scalar(
            engine,
            "SELECT id FROM position_snapshots WHERE account_id = :account_id "
            "AND source = 'manual' AND status = 'accepted' "
            "ORDER BY accepted_at DESC NULLS LAST, revision DESC, updated_at DESC, "
            "created_at DESC, id DESC LIMIT 1",
            account_id=account_id,
        )
        by_source: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            by_source.setdefault(str(row["source"]), []).append(row)
        manual_rows = by_source.get("manual", [])
        if selected_id is not None:
            by_source["manual"] = [
                row for row in manual_rows if row["id"] != selected_id
            ] + [row for row in manual_rows if row["id"] == selected_id]

        updates: list[tuple[object, int, str]] = []
        for source, source_rows in by_source.items():
            for revision, row in enumerate(source_rows, start=1):
                old_status = str(row["status"])
                new_status = (
                    "accepted"
                    if row["id"] == selected_id
                    else "superseded"
                    if source == "manual" and old_status == "accepted"
                    else old_status
                )
                updates.append((row["id"], revision, new_status))

        for offset in range(0, len(updates), batch_size):
            batch = updates[offset : offset + batch_size]
            params: dict[str, object] = {}
            revision_cases: list[str] = []
            status_cases: list[str] = []
            ids: list[str] = []
            for index, (snapshot_id, revision, status) in enumerate(batch):
                params[f"id_{index}"] = snapshot_id
                params[f"revision_{index}"] = revision
                params[f"status_{index}"] = status
                revision_cases.append(f"WHEN :id_{index} THEN :revision_{index}")
                status_cases.append(f"WHEN :id_{index} THEN :status_{index}")
                ids.append(f":id_{index}")
            statement = (
                "UPDATE position_snapshots SET revision = CASE id "
                + " ".join(revision_cases)
                + " ELSE revision END, status = CASE id "
                + " ".join(status_cases)
                + " ELSE status END WHERE id IN ("
                + ", ".join(ids)
                + ")"
            )
            _execute_one(engine, statement, **params)

        _execute_one(
            engine,
            "UPDATE accounts SET current_position_revision = :revision, "
            "current_position_snapshot_id = :snapshot_id WHERE id = :account_id",
            revision=len(manual_rows),
            snapshot_id=selected_id,
            account_id=account_id,
        )


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
                if step.kind != "backfill" and not _is_complete(engine, step):
                    raise MigrationPlanError(
                        f"Applied DSQL object is missing at {step.object_name}"
                    )
                continue

            if step.kind == "backfill":
                _backfill_manual_revisions(engine)
            elif not _is_complete(engine, step):
                if _object_exists(engine, step) and step.kind not in {
                    "drop_constraint",
                    "async_alter",
                }:
                    raise MigrationPlanError(
                        f"Incompatible pre-existing DSQL object at {step.object_name}; "
                        "refusing to adopt it."
                    )
                result = _execute_one(engine, step.statement)
                if step.kind in {"index", "async_alter"}:
                    if result is None:
                        raise RuntimeError(
                            "Aurora DSQL did not return an asynchronous job id "
                            f"for {step.key}"
                        )
                    _wait_for_index(engine, result)
                if not _is_complete(engine, step):
                    raise MigrationPlanError(
                        "Aurora DSQL object does not match expected definition after "
                        f"{migration.revision}/{step.key}"
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
