# 04 — Validation and Acceptance

The migration is complete only when the repo has one coherent current architecture and preserves working Finance behavior. Passing a few unit tests is not sufficient.

## 1. Baseline and regression discipline

Before editing, record the current results of the repository-defined quality commands where practical. The reviewed snapshot defines `pnpm check` as the aggregate local quality gate and has separate browser journeys.

After the rewrite, rerun the equivalent full suite. Do not hard-code historical test counts as acceptance criteria; use the live repo's current test inventory.

Required categories:

- generated OpenAPI/TypeScript contract freshness;
- ESLint/Ruff/format/type checks;
- backend unit/API/integration tests;
- frontend unit tests and production build;
- infrastructure contract tests;
- browser/E2E journeys where the disposable database opt-in is available.

## 2. PostgreSQL/Alembic

Required:

- fresh PostgreSQL 16 database -> `alembic upgrade head` succeeds;
- representative populated older revision -> head succeeds without losing preserved data/history;
- current schema tests pass with PostgreSQL-specific constraints/JSONB/NUMERIC/FK behavior;
- migration head contains all required schema semantics previously represented by the parallel DSQL plan;
- no application path depends on `DATABASE_BACKEND=aurora_dsql` or DSQL migration code.

Neon credentialed checks when available:

- clean Alembic migration using the intended migration connection;
- runtime CRUD/transaction smoke using the app connection;
- connection recycle/reconnect after idle/cold conditions;
- representative concurrent-write/retry case where the app expects retries;
- pool sizing/concurrency does not exceed the configured personal-project envelope.

If Neon credentials are unavailable, mark these checks pending—never substitute mocked DSQL/Neon behavior for real cloud evidence.

## 3. Core product regression

Walk the capability map discovered in the audit, not merely stage labels. At minimum preserve all currently working local/offline behavior that the live release records establish, including relevant examples such as:

- accounts/manual positions and immutable revisions;
- reviewed position/fund imports;
- valuation and reconciled ETF look-through exposure;
- frozen reports/export;
- existing transaction/category/split/transfer behavior;
- finance summaries/balances;
- history/performance;
- tax-lot and hypothetical planning workflows;
- manual/offline research, frozen context, notes/watchlists, and evidence validation;
- current auth/session logic;
- local PDF job behavior that is actually delivered.

Do not turn partial/gated capabilities into false completion claims.

## 4. Storage

Local:

- all `PrivateFileStore` tests continue to pass.

GCS implementation:

- safe key validation;
- bounded upload/download;
- content length/hash verification;
- duplicate/idempotency behavior;
- no public URL dependency;
- failed/malformed reads clean up streams/resources;
- storage errors map to safe domain/API errors;
- real GCS smoke only when credentials/bucket are explicitly available.

Private PDF/document preview must still flow through authenticated backend routes in hosted mode.

## 5. Authentication and edge routing

Validate locally/unit level:

- OIDC configuration validation;
- exact issuer/subject/scope restrictions;
- secure session cookies;
- origin/CSRF behavior;
- logout revocation;
- unauthorized responses clear private frontend state;
- auth/database failures remain redacted and request-correlated.

Credentialed hosted checks when available:

- Firebase Hosting SPA load;
- `/api/health` and `/api/health/ready` route correctly to Cloud Run;
- OIDC callback route works through the public same-origin path;
- private API route requires valid app authentication;
- direct Cloud Run access cannot bypass backend authorization.

## 6. Jobs

Preserve tests for:

- durable enqueue/idempotency;
- claim ownership/generation;
- lease expiry/stale completion fencing;
- cancellation;
- bounded retry/exhaustion;
- no external/filesystem/parser work inside retryable DB transactions;
- no duplicate publication after repeated execution/triggering.

If Cloud Run Job triggering is implemented, add tests for safe repeated trigger attempts and one-shot worker exit behavior. Run a real Cloud Run Job smoke only when a target project is available.

## 7. Infrastructure

Current IaC must describe GCP, not AWS.

Validate:

- formatting/provider/schema validation;
- no accidental apply during tests;
- least-privilege runtime service account;
- GCS not public;
- Secret Manager references instead of embedded secrets;
- Cloud Run resource bounds/scaling configuration are explicit;
- Artifact Registry image is source/version bound for promotion;
- frontend/API routing configuration is reproducible;
- cost-alert assumptions are dated and do not claim a hard zero-cost ceiling.

## 8. Recovery and release gates

Encrypted archive/recovery tests must continue to cover:

- integrity/tamper failure;
- scoped export;
- isolated restore;
- idempotent/repeat behavior;
- no secrets or private data in logs/evidence.

New cloud evidence should be bound to Neon/GCP, not DSQL/AWS. Any remaining release gate must fail closed when required real-cloud evidence is absent.

## 9. Personal AI / research boundary

The migration should not change the functional gate unless separately authorized.

Verify:

- default runtime still makes no Personal AI call;
- `PersonalAIClient`/research evidence boundaries remain explicit;
- finance validation remains authoritative;
- no private statement/portfolio/thesis content is transmitted merely because both services happen to run on GCP;
- live retrieval/synthesis/monitoring completion claims remain accurate.

## 10. Documentation consistency

Current-facing docs must agree on:

```text
Local DB: PostgreSQL 16
Cloud DB: Neon PostgreSQL
API: Cloud Run
Private files: GCS
Frontend: Firebase Hosting (unless the migration records an approved simpler equivalent)
Images: Artifact Registry
Secrets: Secret Manager
Auth: existing provider-neutral OIDC design
AI: shared Personal AI boundary, still separately gated
```

Historical AWS/DSQL evidence may remain only when clearly labeled as historical/superseded.

## 11. Final stale-provider search

Search the entire repository for active AWS/DSQL identifiers. Every current-code/current-doc match must be justified or removed.

Also search for stale GCP migration placeholders such as `TODO`, `TBD`, fake project IDs, sample buckets, disabled validation, or skipped tests that accidentally became part of a claimed release gate.

## Definition of done

The rewrite is done when:

1. local/offline Finance behavior is not regressed;
2. standard PostgreSQL/Alembic is the only active database architecture;
3. production config targets Neon/GCP and starts fail-closed with valid new settings;
4. GCS replaces S3 behind the existing storage contract;
5. AWS Terraform/release machinery has a coherent GCP/Neon replacement rather than dead parallel scaffolding;
6. auth, recovery, jobs, and operational safeguards survive the provider change;
7. docs/plans instruct future Codex sessions to use the new architecture;
8. all available local validation passes;
9. unavailable credentialed checks are explicitly pending, not silently claimed;
10. the final report lists intentional historical AWS references and any remaining non-migration gaps.
