# Aurora DSQL compatibility contract

**Status:** DSQL boundary implemented; live cluster remains unverified | **Verified against AWS/PyPI official documentation:** 2026-10-02
**Architecture:** PostgreSQL 16 locally and for personal/offline operation; **single-Region Amazon Aurora DSQL in production**. The same FastAPI domain logic must support both. No claim is made that a live DSQL cluster has been tested yet.

This file is the authoritative DSQL-specific companion to [`02-architecture.md`](02-architecture.md), [`05-roadmap.md`](05-roadmap.md), and [`06-security-and-deployment.md`](06-security-and-deployment.md). Recheck the official links before implementing: Aurora DSQL is adding PostgreSQL features frequently.

## 1. Why this split

- **Local:** Docker Compose runs PostgreSQL 16; no AWS credentials, API spend or connectivity needed. Local PostgreSQL is a complete personal deployment, not merely a disposable test database.
- **Production:** Aurora DSQL is the required SQL database. As checked 2026-09-25, its ongoing monthly free allowance is **100,000 DPUs plus 1 GB-month of storage**; excess usage is billable. This is an *account/organization-level allowance*, not a promise of a free cluster in every Region or a free full AWS stack. [Official pricing](https://aws.amazon.com/rds/aurora/dsql/pricing/).
- **Shared:** One schema *logical model*, Pydantic contracts, exposure engine and import/business logic. Small, explicit database-specific adapters handle engine/authentication, migration quirks and worker job claiming. The UI is identical.
- **Avoid two apps:** Production code must be covered by real Aurora DSQL smoke/integration tests. Local PostgreSQL passing on its own is insufficient evidence of production compatibility.

## 2. Shared technology and configuration

- Python 3.12+; FastAPI; Pydantic v2; SQLAlchemy 2; Alembic; psycopg 3; PostgreSQL 16 for local; Aurora DSQL connector/SQLAlchemy dialect for production.
- Favor UUID primary keys generated in application code and SQLAlchemy `NUMERIC`/Python `Decimal` for all financial values. Use explicit timestamps, currencies, `VARCHAR`/`TEXT`, UUID, boolean and `JSONB` for *small* provider metadata; avoid reliance on unsupported extension types.
- Separate `DatabaseEngineFactory` configurations conceptually:

```dotenv
# Local only
DATABASE_BACKEND=postgres
DATABASE_URL=postgresql+psycopg://app:local-only@127.0.0.1:5432/portfolio

# Production only (illustrative; do not copy real values into Git)
# DATABASE_BACKEND=aurora_dsql
# AWS_REGION=us-west-2
# AURORA_DSQL_CLUSTER_ENDPOINT=<cluster-endpoint>
# AURORA_DSQL_DB_USER=<least-privilege-application-role>
# AURORA_DSQL_MIGRATION_DB_USER=<separate-schema-migration-role>
# AWS credentials from task/instance role, never an embedded AWS key
# DATABASE_POOL_SIZE=5
# DATABASE_MAX_OVERFLOW=5
# DATABASE_POOL_RECYCLE_SECONDS=3000
```

- As checked on 2026-10-01, PyPI's current AWS SQLAlchemy dialect is `aurora-dsql-sqlalchemy` **1.3.0** (released 2026-09-24); the locked Python connector is **0.2.7**. The implementation requires the official `create_dsql_engine` helper, psycopg 3, and `psycopg[binary,pool]`; see [dialect documentation](https://pypi.org/project/aurora-dsql-sqlalchemy/) and [connector documentation](https://pypi.org/project/aurora-dsql-python-connector/). The helper obtains IAM tokens when opening connections and defaults to TLS certificate and hostname verification (`sslmode=verify-full`, `sslrootcert=system`).
- Configure AWS Region, cluster endpoint and a scoped application role. `DATABASE_URL` is rejected for DSQL so a password or stale token cannot be embedded in a URL. `AURORA_DSQL_MIGRATION_DB_USER` must differ from the app role and is required by the migration command. AWS credentials come from the standard AWS credential chain or an assigned workload role. [AWS token guide](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_authentication-token.html), [TLS guidance](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/configure-root-certificates.html).
- The engine pool defaults to 5 connections plus at most 5 overflow connections. Connection attempts time out after 3 seconds, pool checkout after 3 seconds, and pooled connections recycle after 3,000 seconds, below DSQL's documented 60-minute maximum connection duration. Readiness uses the selected SQLAlchemy engine, including DSQL; health checks do not call external services.
- Use one cluster's built-in `postgres` database in production. Use schemas if justified but be aware of [DSQL quotas](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/CHAP_quotas.html).

## 3. SQL compatibility: design for the intersection

| Concern | DSQL-compatible choice | Avoid or isolate |
| --- | --- | --- |
| Keys / relationships | App-generated UUIDs; supported foreign keys, uniqueness and joins | PostgreSQL-specific functions/triggers for IDs; assuming `SERIAL` behavior is identical |
| Numeric / JSON | `NUMERIC`, `UUID`, `JSONB` for bounded metadata; keep raw artifacts in files/S3 | Massive JSON blobs and unsupported PostgreSQL extensions |
| Aggregation | Portable `JOIN`, `GROUP BY`, CTEs, decimal calculations, simple window queries supported by both | Unverified PostgreSQL-only functions, procedures or index operators |
| Data manipulation | Idempotent upserts when verified, explicit transaction boundaries | Reliance on triggers, `TRUNCATE`, or temporary tables |
| Schema changes | Versioned DSQL migration runner with separate transactions | Applying PostgreSQL Alembic migration unchanged |
| Indexes | DSQL `CREATE INDEX ASYNC` with readiness verification | Treating an index as immediately available after DDL starts |
| Research search | Shared personal-AI retrieval; finance validates and stores only needed source/result references | Requiring `pgvector`, GIN/`tsvector` or any extension in DSQL |

**Feature-state corrections:** AWS's current SQL/type references support foreign keys and their `CASCADE`, `RESTRICT`, and `SET NULL` actions, `CHECK` constraints, UUID, NUMERIC, and JSONB. The core model's `NUMERIC(24,10)` and `NUMERIC(28,10)` fit current limits. Verify [release notes](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/release-notes.html) before treating an older limitations list as current. [Supported SQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-sql-features.html), [data types](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-data-types.html).

Generic research indexing/retrieval belongs in `personal-ai-system` per [ADR 0001](adr/0001-shared-personal-ai.md). Finance stores canonical financial state and validated source/result references; integration adds no new datastore or SQL-extension dependency. The following restrictions remain for any finance-owned SQL work.

Do not assume **PostgreSQL extensions** work: Aurora DSQL is managed and does not expose PostgreSQL extension catalogs as a supported general extension-install mechanism. Do not create a finance-owned pgvector/research runtime to duplicate the shared AI service.

## 4. Transaction design and ingestion

### Stage 0.4 core schema migration plan and evidence

The PostgreSQL Alembic revision `0001_core_portfolio_schema` creates `issuers`, `accounts`, `issuer_aliases`, `securities`, `position_snapshots`, `quotes`, and `position_snapshot_lines`. The separate, versioned DSQL plan in `app/db/dsql_migrations.py` mirrors that schema with seven table steps and four asynchronous index steps. Migration `0003_immutable_position_revisions_and_identifiers` adds the eighth table, three more asynchronous indexes, scoped identifier/alias identity, immutable selected revisions, and a bounded revision/counter backfill; it has not been run on a live cluster. The current SQLAlchemy metadata compiles eight tables and five explicit indexes through the official DSQL dialect locally without opening a connection.

The Stage 0.5 Alembic revision `0002_position_snapshot_revision` adds `accounts.current_position_revision` and `position_snapshots.revision`, both with portable integer defaults. A follow-up migration adds namespace-scoped security identifiers and issuer-alias review fields, an explicit account current-snapshot pointer, unique per-account snapshot revisions, and removes the one-row-per-effective-date identity constraint. Replacement inserts a new revision and moves the pointer in the same transaction. Prior revision payloads and lines are immutable; lifecycle status may transition from accepted to superseded. The follow-up upgrade deterministically reconciles existing accepted snapshots and account counters. PostgreSQL migrations `0001` and `0002` remain immutable.

Migration ledger checksums retain the original executable-step algorithm for compatibility with recorded 0001/0002 steps. Evolving schema validation metadata does not change prior checksums; object definitions are checked independently on resume.

The DSQL runner creates a migration ledger in its own DDL transaction, executes each table, alter or index DDL statement in a separate transaction, waits for each asynchronous index job, then records that step with separate DML. It checksums statements and validates expected columns, types, nullability, constraints and index key definitions before adopting an unrecorded pre-existing object. Incompatible drift fails with the migration and object name; it is never treated as complete because a name exists. Data backfills use idempotent, bounded DML transactions separate from DDL. An unfinished invalid index created by the plan is removed in its own DDL transaction before retry. For constraint validation, DSQL adds the FK as `NOT VALID`, then runs `ALTER TABLE ASYNC ... VALIDATE CONSTRAINT` and waits for its job before recording completion, following [AWS's documented ALTER TABLE syntax](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/alter-table-syntax-support.html). Alembic continues to reject `DATABASE_BACKEND=aurora_dsql` and cannot send PostgreSQL migrations to DSQL. The actual DSQL command is `uv run --directory services/api --locked python -m app.db.migrate_dsql` with both configured roles and the AWS credential chain available.

Stage 3.1 adds `investment_events` in PostgreSQL migration `0012_stage3_investment_events` and the corresponding DSQL step with separate asynchronous account/date and security/date indexes. Structural plan coverage plus gated synthetic PostgreSQL/DSQL event round trips are checked in. These additions are not evidence of a live DSQL migration or data round trip; see [Stage 3 release status](stage-3-release.md).

Stage 3.2 adds reviewed tax-lot imports, raw staged rows, published lots, append-only adjustments, and review audit events in PostgreSQL migration `0013_stage3_tax_lots` and the matching DSQL plan. The plan has one table/index statement per step and waits for each async index before dependent work. Structural plan tests and an opt-in live-DSQL lot/adjustment round trip are checked in. Neither gated tests nor local SQLite checks establish live DSQL or PostgreSQL migration evidence; see [Stage 3 release status](stage-3-release.md).

Stage 3.3 adds a read-only sale-simulation endpoint over the existing position, quote, lot, adjustment and investment-event records; it adds no schema or migration. The implementation uses portable SQLAlchemy selects and performs no canonical writes. Synthetic SQLite API tests validate the calculation and warning boundaries, but neither those tests nor generated DSQL dialect/migration checks establish live PostgreSQL or DSQL runtime behavior. See [Stage 3 release status](stage-3-release.md).

Stage 3.4 adds a read-only hypothetical portfolio-scenario endpoint over existing account, position, quote, security and published fund records. It adds no schema or migration and performs no canonical writes. Its SQLAlchemy queries use portable selects. Synthetic SQLite API tests cover scenario calculations and unchanged position revisions; they do not establish live PostgreSQL or DSQL runtime behavior. See [Stage 3 release status](stage-3-release.md).

As verified on 2026-10-01, [AWS DSQL limits](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/CHAP_quotas.html) include **10 MiB of changed data**, **3,000 modified rows**, **five minutes per transaction**, and **60 minutes per connection**. DSQL uses optimistic concurrency and fixed Repeatable Read isolation; conflicting transactions may abort and need a whole-unit retry. These are upper limits, **not** recommended targets.

- Keep transaction scopes brief. Prefer batches of a few hundred rows (configurable and measured), with a safety margin for secondary-index changes, provider payload size and latency. Never hold a transaction open while downloading a PDF, calling AI, fetching holdings, or waiting for review.
- Stage parsed data in `imports` and line tables. Preserve original documents/files privately and compute source hash and idempotency key **before** transaction commit. Commit each bounded import batch idempotently; publish the completed position/fund snapshot only after all batches validate.
- For large imports, write to a `PENDING` snapshot identifier in bounded commits; a final small transaction marks it `ACTIVE`. All normal portfolio queries filter for a fully published revision. On failure, rerun only uncommitted batches; schedule cleanup of orphaned staging data.
- `app/db/transactions.py` retries SQLSTATE `40001` and DSQL `OC001` only, with a fresh session per attempt, at most three attempts by default (five maximum), and capped exponential backoff with jitter. The helper contract is database-only; provider/model/file work must finish before the retried unit begins.
- DSQL handles [DDL separately from DML](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-ddl.html); only one DDL statement per transaction. `CREATE INDEX ASYNC` needs a waiting/verification step before subsequent migration assumptions. Adapt Alembic or write explicit DSQL migration sequences; keep a versioned migration ledger and test fresh-install plus upgrade from previous schema versions.

**Verification status:** local configuration, engine-factory, dialect-compilation, migration-plan/resumption, schema-drift, and bounded-retry tests pass. The credentialed suite at `services/api/tests/test_dsql_integration.py` is opt-in (`RUN_DSQL_INTEGRATION=1`, `DSQL_TEST_CLUSTER=disposable`) and includes migration, synthetic CRUD, decimal/UUID/JSONB/FK behavior, OCC retry, manual same-date replacement/history/rollback, and scoped identifier/alias uniqueness. Live populated-upgrade preservation, IAM reconnection after token expiry, and the expanded suite have not yet been run because no disposable AWS DSQL cluster was provided. **DSQL remains unverified and production remains blocked.**

## 5. Background tasks without PostgreSQL lock dependence

For **Stage 1**, scheduled CLI refresh commands or single-process APScheduler are enough locally; avoid introducing queues solely to copy cloud architecture. For **Stage 2**, implement a `JobRunner`/`JobStore` interface with `enqueue`, `claim`, `renew`, `complete`, `fail` and an idempotency key. Options:

- **Local:** single-worker polling. The current PDF preview worker runs inside the API lifespan and claims jobs with conditional updates plus an owner/generation fence; it does not use `SKIP LOCKED`.
- **Production:** prefer SQS + a small worker or a proven optimistic database lease with conditional `UPDATE ... WHERE status = 'pending' AND lease_until < now()` followed by a check of rows affected. Bound transaction and retry on OCC; design for at-least-once processing and expired leases. Do not assume `SELECT FOR UPDATE SKIP LOCKED` is supported or has identical behavior on DSQL without dedicated integration tests.
- Whichever implementation: ensure retries cannot duplicate imported transactions, fund snapshots, notifications, or research charges.

The local queue schema and runner are not evidence of DSQL lease correctness. Before using the optimistic lease with Aurora DSQL, run real concurrent-claim, lease-expiry, stale-completion, cancellation and retry tests on a disposable DSQL cluster. The current application uses a local in-process worker only; no SQS or production worker deployment is configured.

SQS, Lambda, schedules, VPC interface endpoints and log ingestion can incur their own charges. They are *not* included in DSQL's database allowance.

## 6. Storage, research retrieval and cost

- Store only active structured data, a small amount of raw provider metadata, and carefully selected historical snapshots in DSQL; originals go to **private S3** (local filesystem offline). Archive old source snapshots as compressed, dated files when appropriate without destroying auditability or historical computations.
- Monitor *logical database storage*, not just file upload sizes. 1 GB is the DSQL monthly free storage quantity in AWS's current pricing text. Monitor DPU burn from refreshing ETF holdings, full-table aggregate exposure queries, parsing imports and any scheduled research jobs.
- The DSQL allowance is applied monthly at the account/organization level according to the current [pricing FAQ](https://aws.amazon.com/rds/aurora/dsql/pricing/); **charges apply to excess storage and usage**. Use a single-region cluster. Multi-region replicas multiply storage and replicated-write usage.
- Vectors and full-text search are **not finance Stage 1 requirements**. Stage 5 delegates generic passage retrieval/indexing/ranking to personal-AI, while finance validates returned source/issuer/date metadata and retains necessary result references. Do not build duplicate retrieval infrastructure or production research dependent on unsupported DSQL extension semantics.
- Budget the *entire* AWS topology separately: application compute, S3, CloudFront, TLS/domain, optional SQS/Lambda, CloudWatch, optional PrivateLink, data transfer and AWS Backup. **Free DSQL does not mean free deployment.** Billing alarms notify; they do not forcibly stop overruns.

## 7. Production security and recovery

- Use an application-specific IAM role + DSQL `dsql:DbConnect` mapped to a least-privilege DB role; use admin connections only for tightly scoped schema management.
- Enforce TLS with certificate and hostname verification. Choose public service endpoint with strict IAM+TLS and tight app-network egress, or a [DSQL PrivateLink connection endpoint](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/privatelink-managing-clusters.html) if private networking is required and recurring endpoint charges are acceptable. **Do not describe DSQL as a conventional RDS instance in a private subnet.**
- [AWS Backup supports DSQL backup/restore](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/disaster-recovery-resiliency.html), but has a separately priced service. Also provide encrypted portable exports of the app's structured records plus S3 source files, test restoring into a new cluster/local PostgreSQL, and document non-portable vendor metadata.
- Cloud deployment requires user authentication on app routes, private S3, no raw statement logs, scoped secrets, and teardown/usage checks. A budget alert is not a cap.

## 8. DSQL readiness test matrix (required before any production deployment)

| Test | Local PG 16 | Real DSQL test cluster |
| --- | --- | --- |
| Create / upgrade full schema, including indexes, FKs and uniqueness | Required | **Required** |
| Connect with appropriate credentials, long-lived pool/new connection after 15-minute token expiry | Password local | **IAM token refresh + TLS** |
| `Decimal` value and UUID/JSONB round-trips | Required | **Required** |
| Same position snapshot imported twice | Required | **Required** |
| Manual same-date replacement appends a revision and retains previous lines; rollback preserves selected pointer | Required | **Required** |
| Populated upgrade with multiple accounts/dates, accepted and superseded snapshots, identifiers and aliases | Required | **Required** |
| Scoped identifier/alias uniqueness and unresolved cross-issuer ambiguity | Required | **Required** |
| Existing table/column/constraint/index definition drift is rejected before adoption | Mock and structural tests | **Required** |
| New IAM-authenticated connection after a token expires; TLS hostname verification | N/A | **Required** |
| 500-row ETF import and subsequent revision publish | Required | **Required** |
| Inject OCC conflict and assert bounded retry / idempotency | Simulate | **Required** |
| Query exposure NAV and unknown residual; both match golden fixture | Required | **Required** |
| Intentionally exceed a configured safe batch to ensure failure leaves no visible half-snapshot | Required | **Required** |
| Queue retry/lease expiration, if worker implemented | Required | **Required** |
| AWS cost and backup/export drill | N/A | **Required** before real data |

CI runs all local tests on ordinary PRs. Run DSQL integration smoke tests on a gated workflow using ephemeral/test-only credentials and a deliberately capped small fixture, or run them manually before promotion if ongoing cloud CI would violate the budget. Never falsely mark DSQL compatibility as tested when the cloud suite was skipped.

The DSQL live contract remains intentionally broader than the current opt-in suite: populated-upgrade preservation and IAM token-expiry reconnection are still pending explicit live tests/evidence. Do not count the new local schema-drift unit tests as live DSQL evidence.

## 9. Official reference index

- [DSQL pricing and monthly allowance](https://aws.amazon.com/rds/aurora/dsql/pricing/)
- [PostgreSQL migration guide and compatibility caveats](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-migration-guide.html)
- [Supported SQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-sql-features.html) and [supported types](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-data-types.html)
- [Current cluster quotas and transaction limits](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/CHAP_quotas.html)
- [Official SQLAlchemy dialect](https://github.com/awslabs/aurora-dsql-orms/tree/main/python/sqlalchemy)
- [IAM login tokens](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_authentication-token.html)
- [DDL and distributed transactions](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-ddl.html)
- [Release notes](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/release-notes.html)
- [PrivateLink network option](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/privatelink-managing-clusters.html)
