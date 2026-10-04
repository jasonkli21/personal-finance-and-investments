# 03 — Migration Execution Plan

This is intended to be executed end to end in one Sol High session after the live audit.

## M0 — Protect the baseline

- Confirm branch/worktree status and preserve unrelated user changes.
- Record current commit and baseline validation results.
- Do not create dual-write/cutover code unless live resources/data actually exist.
- Verify the repo's current claim that no AWS resources have been provisioned.

## M1 — Build the concrete migration map

Using the audit checklist, classify each cloud-coupled area as:

- **preserve unchanged** — domain logic, OIDC design, FileStore protocol, local Postgres, etc.;
- **generalize** — DB retry helper, production configuration, worker entrypoints;
- **replace** — DSQL engine with ordinary Postgres/Neon, S3 implementation with GCS, AWS Terraform with GCP;
- **retire** — DSQL migration/evidence/token machinery, App Runner helper scripts;
- **historical only** — dated AWS release evidence retained with a clear superseded marker.

## M2 — Establish the new architecture decision before code drifts

Add/update an ADR or equivalent current architecture decision that supersedes Aurora DSQL/AWS as the production target.

It should establish:

- GCP as the deployment cloud;
- Neon PostgreSQL as deployed relational storage;
- local PostgreSQL 16 retained;
- Alembic as the shared migration path;
- Cloud Run API;
- GCS private files;
- Firebase Hosting/same-origin `/api` routing;
- Artifact Registry + Secret Manager + service account/IAM;
- existing OIDC retained;
- durable Finance jobs preserved, with Cloud Run Jobs only as execution infrastructure;
- Personal AI remains separately gated.

## M3 — Collapse database support to standard PostgreSQL

### M3.1 Configuration

Refactor `app/config.py` and `.env.example` so production no longer requires:

- `DATABASE_BACKEND=aurora_dsql`;
- `AWS_REGION`;
- `AURORA_DSQL_*` users/endpoints;
- DSQL-specific pool/token lifecycle values.

Prefer normal PostgreSQL configuration:

- `DATABASE_URL` for runtime;
- optional `MIGRATION_DATABASE_URL` if a direct Neon endpoint is required for Alembic;
- production TLS requirements validated explicitly;
- bounded pool sizing appropriate for Cloud Run and Neon.

Keep local discrete Postgres fields if they remain useful for Compose.

### M3.2 Engine

Simplify `DatabaseEngineFactory` to the ordinary PostgreSQL path. Preserve pool pre-ping, bounded pool configuration, connect timeout, and testability.

Remove `aurora-dsql-sqlalchemy` and related connector dependencies after all references/tests are migrated.

### M3.3 Migration parity and retirement

This is a mandatory safety step because the repo has 18 Alembic revisions and a large independent DSQL plan.

- Compare Alembic head against the DSQL plan's intended schema/constraints/indexes/backfills.
- Document any real semantic differences.
- Ensure the canonical Alembic path contains every schema rule that Finance actually requires.
- Add/strengthen fresh-install and representative populated-upgrade tests if parity is not already covered.
- Then remove `dsql_migrations.py`, `migrate_dsql.py`, DSQL schema ledger/evidence helpers, and DSQL-only tests.

Do not preserve the parallel migration system merely because it is large.

### M3.4 Transaction semantics

Preserve `run_database_unit`'s important discipline:

- retry only repeatable DB-only units;
- external API/AI/filesystem work remains outside retries;
- bounded attempts and jitter.

Remove DSQL `OC001` recognition. Retain standard PostgreSQL serialization/deadlock handling only if current code/tests justify it.

Review DSQL-driven batch limits one by one. Keep limits that protect memory, payload size, latency, data review, or Cloud Run/Neon behavior; remove limits that exist solely because of DSQL transaction restrictions.

## M4 — Replace S3 with GCS behind the existing storage interface

- Keep `FileStore` and `PrivateFileStore`.
- Implement `GCSFileStore` with equivalent integrity/privacy bounds.
- Update `storage/factory.py` and settings from `local|s3` to `local|gcs`.
- Replace S3/KMS/bucket settings with GCS bucket/project settings only where required.
- Prefer workload identity/ADC in Cloud Run; no service-account JSON files in repo or runtime configuration.
- Rewrite storage tests, including duplicate/integrity/oversize/stream cleanup/error behavior.
- Preserve backend-mediated private file preview/download.

## M5 — Preserve and rewire authentication/edge behavior

Do not rewrite the existing OIDC authentication subsystem unless a real incompatibility is found.

- Keep PKCE, issuer/audience/nonce validation, allowed subject/scope, DB sessions, secure cookies, logout revocation, request correlation, and origin checks.
- Replace CloudFront edge assumptions with Firebase Hosting/Cloud Run routing.
- Preserve a same-origin `/api` public path so browser/API cookies and OIDC callback behavior stay simple.
- Update `APP_PUBLIC_ORIGIN` and deployment docs/tests accordingly.
- Ensure the direct Cloud Run origin is not treated as a bypass around backend authentication.

## M6 — Port the durable job execution model

Local behavior should continue to use the current durable job row + worker.

For cloud:

- add a bounded one-shot worker command/entrypoint around existing claim/process logic;
- if hosted document jobs are in target scope, have the API trigger a Cloud Run Job after durable enqueue using a safe idempotent pattern;
- allow repeated triggers without duplicate publication because the DB job fence remains authoritative;
- retain cancellation/generation/lease protections;
- do not add Pub/Sub, Cloud Tasks, or another queue unless the implementation proves Cloud Run Jobs cannot safely satisfy the current workflow.

Do not claim Stage 2 job completion merely because the execution platform changed. Preserve documented partial acceptance gaps unless explicitly proven fixed.

## M7 — Rewrite infrastructure from AWS to GCP

Replace `infra/terraform` and related scripts/contracts so current infrastructure expresses the new target.

Retire/replace:

- Aurora DSQL;
- S3 private/static buckets;
- CloudFront/OAC/functions;
- ECR;
- App Runner;
- AWS IAM policies/roles;
- AWS budget resources;
- App Runner log-retention helper.

Introduce only the GCP resources actually needed:

- Artifact Registry;
- Cloud Run API;
- optional Cloud Run Job;
- dedicated runtime service account and minimal IAM;
- GCS private bucket;
- Secret Manager references;
- frontend hosting/routing configuration;
- relevant logging/retention and cost-alert documentation/configuration.

Keep infrastructure tests in `tests/infra` and rewrite their contracts rather than deleting the test layer.

## M8 — Rewrite Stage 4 recovery/release machinery

Preserve useful operational safeguards while deleting DSQL/AWS-specific ceremony.

### Recovery

- keep encrypted portable archive/export and isolated local restore;
- replace S3/DSQL cloud drill assumptions with GCS/Neon;
- preserve tamper detection, idempotency, scope confirmation, and explicit retention/RTO/RPO decisions.

### Release evidence

Refactor or replace `app/release/dsql_evidence.py` and `stage4_gate.py` with evidence appropriate to Neon/GCP, such as:

- clean schema migration on Neon;
- representative populated migration/roundtrip;
- pooled app reconnect after idle/cold conditions;
- concurrency/retry behavior actually used by Finance;
- private GCS access through authenticated API;
- OIDC HTTPS journey;
- Cloud Run health/readiness;
- encrypted export/restore drill;
- source/build/schema/config fingerprints where they still add value.

Remove DSQL-only cases such as IAM token-expiry waits, asynchronous index readiness, DSQL migration resumption, and cluster-role identity checks.

## M9 — Reconcile current documentation and plans

Current-facing docs must stop teaching future Codex sessions that DSQL/AWS is mandatory.

At minimum reconcile:

- `AGENTS.md`;
- root `README.md`;
- `docs/README.md`;
- `docs/02-architecture.md`;
- `docs/04-ingestion-and-ai.md` where cloud/job implications changed;
- `docs/05-roadmap.md`;
- `docs/06-security-and-deployment.md`;
- `docs/07-aurora-dsql-compatibility.md`;
- Stage 0–5 implementation plans containing active DSQL assumptions;
- Stage 4 plans/runbooks/cost register/release status;
- maintainability/current-review docs if they are meant to describe the present architecture.

Recommended documentation treatment:

- create a new Postgres/Neon compatibility/deployment contract and update `AGENTS.md` to require it;
- mark the Aurora DSQL compatibility document clearly superseded/historical or relocate it if repo conventions allow;
- update Stage 4's *current target* to GCP/Neon;
- preserve dated AWS test/release facts as historical evidence rather than rewriting history;
- add a migration/rearchitecture record that states what was superseded and why.

Do not advance unrelated product features.

## M10 — Comprehensive validation and repair loop

Run the matrix in `04-validation-and-acceptance.md`. Fix failures caused by the migration, and distinguish true pre-existing gaps from regressions.

## M11 — Final stale-provider and consistency pass

Search code, tests, IaC, scripts, generated config, and current-facing docs for:

```text
AWS
Amazon
Aurora
DSQL
aurora_dsql
boto
S3
CloudFront
App Runner
ECR
IAM ARN
AWS_REGION
AURORA_DSQL_
PRIVATE_S3_
STATIC_ASSETS_BUCKET
OC001
```

Remaining matches must be intentionally historical, migration commentary, or unrelated source references. Current instructions, production code, and active infrastructure must not depend on the superseded provider.

Finish with a migration report covering architecture, major files replaced/retained, capability regressions checked, validation results, cloud checks still pending, and any intentional historical AWS references.
