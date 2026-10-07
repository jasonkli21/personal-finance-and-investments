# 01 — Current-State Audit and Rewrite Scope

## Why an audit is still required

This handoff was informed by public `main` at commit `4e5f3e330a401a4df2f75781689a42300868bdbb`, but Codex must inspect the live checkout because implementation status, uncommitted work, and repository guidance can change.

The audit should be fast but concrete. Its purpose is to prevent two failure modes:

1. treating this as a superficial AWS→GCP rename; or
2. rewriting useful existing boundaries because the handoff failed to notice them.

## Read order

Follow the repository's own hierarchy first:

1. `AGENTS.md`
2. `docs/README.md`
3. current product/architecture/security/roadmap docs
4. stage release/evaluation records, especially Stages 2, 4, and 5
5. `docs/maintainability-review.md`
6. relevant implementation plans only after release evidence/code establishes what is real

The current repo explicitly says plans are not implementation evidence. Preserve that discipline.

## Concrete areas already known to matter

### Database

Inspect:

- `services/api/app/db/engine.py`
- `services/api/app/db/transactions.py`
- `services/api/app/db/dsql_migrations.py`
- `services/api/app/db/migrate_dsql.py`
- `services/api/alembic/**`
- DSQL-specific integration/migration/evidence tests

Observed orientation:

- PostgreSQL already uses the normal SQLAlchemy/psycopg path.
- `DatabaseEngineFactory` cleanly separates `postgres` and `aurora_dsql`.
- `run_database_unit` is largely portable and correctly keeps external/provider work outside retry callbacks; only DSQL-specific conflict recognition should obviously disappear.
- Alembic is the real local schema history; DSQL maintains a large parallel migration plan. Before deleting DSQL code, prove parity so no constraint/index/backfill that matters to the canonical schema is lost.

Create a database delta table with columns such as:

| Existing mechanism | Why it exists | Preserve | Generalize | Replace/remove | Validation |
| --- | --- | --- | --- | --- | --- |
| Alembic migrations | canonical PostgreSQL schema | yes | — | — | fresh + upgrade tests |
| DSQL migration plan | DSQL DDL restrictions | — | maybe historical | retire | parity check |
| `40001` retry | standard serialization conflict | yes | keep generic | — | concurrency tests |
| `OC001` retry | DSQL OCC code | — | — | remove | unit tests |

### Configuration

Inspect `services/api/app/config.py`, `.env.example`, Compose, and tests.

The current production configuration explicitly requires:

- `DATABASE_BACKEND=aurora_dsql`
- AWS region and DSQL roles
- S3 private storage
- a separate static assets bucket
- secure OIDC production settings

This is a core rewrite area, not documentation-only cleanup.

Target direction:

- ordinary PostgreSQL/Neon connection configuration in production;
- production TLS/host validation appropriate for Neon;
- GCS private storage settings;
- GCP service identity/Secret Manager rather than AWS IAM/secret ARNs;
- preserve OIDC fail-closed production auth and secure-cookie/origin requirements.

### Storage

Inspect:

- `app/storage/file_store.py`
- `app/storage/factory.py`
- `app/storage/s3_file_store.py`
- private-file consumers and storage tests

The abstraction already exists. Preserve it. Replace the S3 implementation with a GCS implementation while keeping:

- content-addressed/generated safe keys;
- max read/write bounds;
- hash/size integrity verification;
- no public object URLs for private statements;
- authenticated backend streaming;
- safe duplicate/idempotency behavior.

### Authentication and edge routing

Inspect:

- `app/auth/**`
- `AuthenticationGate.tsx`
- API client/origin handling
- current CloudFront `/api` rewrite behavior in Terraform/docs

Current auth is provider-neutral OIDC with PKCE, server-side sessions, secure cookies, origin/CSRF checks, and a single-person subject/scope boundary. Preserve that design.

Do not introduce Firebase Auth unless the live repo or user explicitly chooses it. Firebase Hosting is a hosting/routing choice, not an identity architecture decision.

The target should preserve a same-origin public surface such as:

```text
https://<app>/          -> SPA
https://<app>/api/**    -> Cloud Run API
```

so current cookie/origin/callback assumptions remain simple.

### Jobs/background work

Inspect:

- `app/domains/jobs.py`
- `app/jobs/runner.py`
- document/PDF routes and ingestion code
- Stage 2 release evidence

The current system already has durable DB job records, optimistic lease owner/generation fencing, cancellation, retry state, and a local worker. Stage 2 correctly marks the broader acceptance surface partial.

Do not replace this with an unrelated cloud queue just because GCP is available. Prefer:

- current in-process/polling worker for local development;
- a bounded one-shot worker entrypoint for Cloud Run Jobs if hosted PDF execution is included;
- the existing database job row as the durable application state;
- explicit trigger/idempotency logic from API to Cloud Run Jobs if implemented.

### Stage 4 infrastructure/release/recovery

Inspect at minimum:

- `infra/terraform/**`
- `scripts/stage4/**`
- `app/release/dsql_evidence.py`
- `app/release/stage4_gate.py`
- `app/recovery/**`
- `docs/stage-4-*`
- `tests/infra/**`

This is a major migration surface. Current Stage 4 machinery includes prepared App Runner/CloudFront/ECR/S3/DSQL/IAM/budget infrastructure, credentialed evidence design, portable encrypted recovery, and fail-closed promotion gates. No AWS resources were provisioned in the reviewed snapshot, which means no live cutover or dual-write path should be invented unless the live checkout proves otherwise.

Preserve the **operational intent** while replacing provider-specific mechanisms:

- DSQL evidence -> Neon/PostgreSQL cloud integration evidence;
- S3 security/recovery -> GCS security/recovery;
- App Runner/CloudFront/ECR -> Cloud Run/Firebase Hosting/Artifact Registry;
- AWS IAM -> GCP service accounts/IAM;
- AWS budgets/cost register -> GCP/Neon cost controls/dated register;
- Stage 4 fail-closed release fingerprinting -> equivalent GCP/Neon fingerprints and smoke evidence where useful.

### Personal AI / research

Inspect:

- `app/integrations/personal_ai.py`
- `app/integrations/research_evidence.py`
- `domains/research.py`
- Stage 5 release/evaluation docs
- ADR 0001

Current Personal AI runtime is intentionally disabled and extraction-only at the protocol boundary. Stage 5 has an offline/manual research baseline and a provisional evidence validator, not live retrieval/synthesis transport.

The cloud rearchitecture must **not** guess a live Personal AI wire contract or transmit private finance context. Keep those gates intact.

## Pre-edit audit output

Before substantive edits, Sol should leave itself a concise repo-local migration note (or update an appropriate existing migration/review doc) containing:

- actual live status of relevant capabilities;
- pre-existing failing checks vs passing baseline;
- concrete AWS/DSQL modules/files;
- preserve/generalize/replace/remove decisions;
- high-risk regression areas;
- whether any real AWS resource/data exists (expected from current docs: none, but verify).

Do not stop for approval after this note unless a destructive ambiguity is discovered.
