# Aurora DSQL compatibility contract

**Status:** Proposed, mandatory for production | **Verified against AWS official documentation:** 2026-09-25  
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
# AURORA_DSQL_DB_USER=<least-privilege-role>
# AWS credentials from task/instance role, never an embedded AWS key
```

- For DSQL use AWS's [Aurora DSQL SQLAlchemy dialect](https://github.com/awslabs/aurora-dsql-orms/tree/main/python/sqlalchemy) (`aurora-dsql-sqlalchemy`) and its `create_dsql_engine` helper or AWS's [Python connector](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_program-with-dsql-connector-for-python.html). Verify package version, driver compatibility, SSL configuration and connection pooling against official examples rather than pasting a static bearer token into a standard database URL.
- DSQL uses IAM-based login tokens (typically **15-minute token validity for *new connections***); a successfully established connection can remain valid after the token expires, subject to DSQL's connection lifetime. Regenerate tokens **when establishing new connections**, use an IAM role assigned to the deployed compute, and verify TLS hostname (`sslmode=verify-full`) in production. [AWS token guide](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_authentication-token.html), [TLS guidance](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/configure-root-certificates.html).
- Use one cluster's built-in `postgres` database in production. Use schemas if justified but be aware of [DSQL quotas](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/CHAP_quotas.html).

## 3. SQL compatibility: design for the intersection

| Concern | DSQL-compatible choice | Avoid or isolate |
| --- | --- | --- |
| Keys / relationships | App-generated UUIDs; supported foreign keys, uniqueness and joins | PostgreSQL-specific functions/triggers for IDs; assuming `SERIAL` behavior is identical |
| Numeric / JSON | `NUMERIC`, `UUID`, `JSONB` for bounded metadata; keep raw artifacts in files/S3 | Massive JSON blobs and unsupported PostgreSQL extensions |
| Aggregation | Portable `JOIN`, `GROUP BY`, CTEs, decimal calculations, simple window queries supported by both | Unverified PostgreSQL-only functions, procedures or index operators |
| Data manipulation | Idempotent upserts when verified, explicit transaction boundaries | Reliance on triggers, `TRUNCATE`, or temporary tables |
| Schema changes | Alembic migration plan with a tested DSQL branch | Assuming a normal multi-DDL migration works unchanged |
| Indexes | DSQL `CREATE INDEX ASYNC` with readiness verification | Treating an index as immediately available after DDL starts |
| Research search | Source metadata filter plus portable application-level text matching or another independently designed search provider | Requiring `pgvector`, GIN/`tsvector` or any extension in DSQL |

**Feature-state corrections:** Aurora DSQL **does support foreign keys** (released August 26, 2026) and **JSONB** (released June 8, 2026). Sequences/identity columns and more DDL operations also exist, but application UUIDs reduce distribution/portability surprises. Verify [release notes](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/release-notes.html) before treating an older limitations list as current. [Supported SQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-sql-features.html), [data types](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-postgresql-compatibility-supported-data-types.html).

Do not assume **PostgreSQL extensions** work: Aurora DSQL is managed and does not expose PostgreSQL extension catalogs as a supported general extension-install mechanism. `pgvector` remains an optional **local PostgreSQL-only experiment** unless the production retrieval design includes a separate portable provider.

## 4. Transaction design and ingestion

### Stage 0.3 core schema migration plan

The local Alembic revision `0001_core_portfolio_schema` creates `issuers`, `accounts`, `issuer_aliases`, `securities`, `position_snapshots`, `quotes`, and `position_snapshot_lines`. It uses application-supplied UUID primary keys, `NUMERIC` quantities/prices/values, bounded JSONB quote metadata, source and quality fields, and relational constraints. The local revision uses PostgreSQL's JSONB type spelling, which DSQL also supports.

The future DSQL migration runner must translate the revision into a versioned DSQL plan: execute each `CREATE TABLE` as its own DDL transaction, then each standalone `CREATE INDEX ASYNC` as a separate DDL transaction and wait for readiness before advancing. DML to update the migration ledger must run only after DDL transactions complete. Fresh install and upgrade paths must verify FK actions, unique/check constraints, JSONB and index readiness on a real cluster. In particular, confirm support for `ON DELETE CASCADE`/`SET NULL` and `CHECK` constraints against current DSQL behavior before using the migration in production. Stage 0.3's local Alembic environment rejects `DATABASE_BACKEND=aurora_dsql` so it cannot accidentally send PostgreSQL migration DDL to DSQL. **No DSQL migration or integration test has run; DSQL is unverified.**

As of 2026-09-25, [AWS DSQL limits](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/CHAP_quotas.html) include **10 MiB of changed data**, **3,000 modified rows** and **five minutes per transaction**. DSQL uses optimistic concurrency and the fixed Repeatable Read isolation level; conflicting transactions may abort and need a whole-unit retry. Connections can expire after 60 minutes. These are upper limits, **not** recommended targets.

- Keep transaction scopes brief. Prefer batches of a few hundred rows (configurable and measured), with a safety margin for secondary-index changes, provider payload size and latency. Never hold a transaction open while downloading a PDF, calling AI, fetching holdings, or waiting for review.
- Stage parsed data in `imports` and line tables. Preserve original documents/files privately and compute source hash and idempotency key **before** transaction commit. Commit each bounded import batch idempotently; publish the completed position/fund snapshot only after all batches validate.
- For large imports, write to a `PENDING` snapshot identifier in bounded commits; a final small transaction marks it `ACTIVE`. All normal portfolio queries filter for a fully published revision. On failure, rerun only uncommitted batches; schedule cleanup of orphaned staging data.
- Retrying after serialization/OCC conflict must start a *new session/transaction* and repeat **only database work**, not re-upload files, re-call models or enqueue duplicates. Use unique idempotency keys and an upper retry bound with exponential backoff/jitter.
- DSQL handles [DDL separately from DML](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/working-with-ddl.html); only one DDL statement per transaction. `CREATE INDEX ASYNC` needs a waiting/verification step before subsequent migration assumptions. Adapt Alembic or write explicit DSQL migration sequences; keep a versioned migration ledger and test fresh-install plus upgrade from previous schema versions.

## 5. Background tasks without PostgreSQL lock dependence

For **Stage 1**, scheduled CLI refresh commands or single-process APScheduler are enough locally; avoid introducing queues solely to copy cloud architecture. For **Stage 2**, implement a `JobRunner`/`JobStore` interface with `enqueue`, `claim`, `renew`, `complete`, `fail` and an idempotency key. Options:

- **Local:** single-worker polling; a conventional PostgreSQL claim implementation can use `SKIP LOCKED` if desired *behind the interface*.
- **Production:** prefer SQS + a small worker or a proven optimistic database lease with conditional `UPDATE ... WHERE status = 'pending' AND lease_until < now()` followed by a check of rows affected. Bound transaction and retry on OCC; design for at-least-once processing and expired leases. Do not assume `SELECT FOR UPDATE SKIP LOCKED` is supported or has identical behavior on DSQL without dedicated integration tests.
- Whichever implementation: ensure retries cannot duplicate imported transactions, fund snapshots, notifications, or research charges.

SQS, Lambda, schedules, VPC interface endpoints and log ingestion can incur their own charges. They are *not* included in DSQL's database allowance.

## 6. Storage, research retrieval and cost

- Store only active structured data, a small amount of raw provider metadata, and carefully selected historical snapshots in DSQL; originals go to **private S3** (local filesystem offline). Archive old source snapshots as compressed, dated files when appropriate without destroying auditability or historical computations.
- Monitor *logical database storage*, not just file upload sizes. 1 GB is the DSQL monthly free storage quantity in AWS's current pricing text. Monitor DPU burn from refreshing ETF holdings, full-table aggregate exposure queries, parsing imports and any scheduled research jobs.
- The DSQL allowance is applied monthly at the account/organization level according to the current [pricing FAQ](https://aws.amazon.com/rds/aurora/dsql/pricing/); **charges apply to excess storage and usage**. Use a single-region cluster. Multi-region replicas multiply storage and replicated-write usage.
- Vectors and full-text search are **not core Stage 1 requirements**. Stage 5 starts with SEC metadata, title/company/filing filters and simple portable matching. If needed, use a distinct `ResearchIndex` interface: local PostgreSQL pgvector and a separately evaluated production search solution, or just local embeddings with small corpora. Do not build production research dependent on unsupported DSQL extension semantics.
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
| 500-row ETF import and subsequent revision publish | Required | **Required** |
| Inject OCC conflict and assert bounded retry / idempotency | Simulate | **Required** |
| Query exposure NAV and unknown residual; both match golden fixture | Required | **Required** |
| Intentionally exceed a configured safe batch to ensure failure leaves no visible half-snapshot | Required | **Required** |
| Queue retry/lease expiration, if worker implemented | Required | **Required** |
| AWS cost and backup/export drill | N/A | **Required** before real data |

CI runs all local tests on ordinary PRs. Run DSQL integration smoke tests on a gated workflow using ephemeral/test-only credentials and a deliberately capped small fixture, or run them manually before promotion if ongoing cloud CI would violate the budget. Never falsely mark DSQL compatibility as tested when the cloud suite was skipped.

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
