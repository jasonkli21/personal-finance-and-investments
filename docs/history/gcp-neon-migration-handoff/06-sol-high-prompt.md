# Sol High Prompt

Use **Sol High** and carry this migration through in one coherent repo-wide session.

Read `finance-gcp-neon-migration-handoff/` first, then read the repository's `AGENTS.md`, docs index, architecture/security/roadmap docs, relevant stage release records, and latest maintainability/review evidence. The live checkout is authoritative. A targeted review of public `main` before this handoff found substantial code through the current stages—including a real local PostgreSQL application, a large parallel DSQL path, prepared Stage 4 AWS infrastructure/recovery/release tooling, and an offline Stage 5 research baseline—but do not infer completion from stage numbers or from this summary. Confirm what is actually delivered, partial, gated, historical, or unverified from code and release evidence.

The goal is to rearchitect the Finance/Investing project from AWS/Aurora DSQL to **GCP + Neon PostgreSQL** end to end, while preserving working finance behavior and the useful existing boundaries. This is not a provider-name replacement.

Before substantive edits, run the current validation baseline where practical and build a concise migration map of **preserve / generalize / replace / retire / historical-only** items. Pay particular attention to the concrete seams already present in the repo:

- `services/api/app/config.py` currently hard-requires DSQL/S3/AWS settings in production;
- `app/db/engine.py` already cleanly separates ordinary PostgreSQL from DSQL;
- Alembic is the local schema history, while `app/db/dsql_migrations.py` / `migrate_dsql.py` implement a large independent DSQL migration path;
- `app/db/transactions.py` contains a mostly portable bounded DB-only retry boundary plus DSQL-specific conflict recognition;
- `app/storage/FileStore` + `storage/factory.py` provide a useful storage abstraction with local and S3 implementations;
- `app/auth/**` is provider-neutral OIDC/PKCE/session logic and should not be replaced merely because Firebase Hosting is used;
- `app/domains/jobs.py` / `app/jobs/runner.py` implement real durable DB job state, leases, cancellation and fencing for local PDF work;
- `infra/terraform`, `app/release/**`, `app/recovery/**`, `scripts/stage4/**`, `tests/infra/**`, and the Stage 4 runbooks contain substantial AWS/DSQL deployment, evidence, cost and recovery machinery;
- `app/integrations/personal_ai.py` and `research_evidence.py` are intentionally gated boundaries, not a live Personal AI transport.

Record the audit/migration map in an appropriate repo document, but **do not stop for review after the audit** unless you hit a genuinely destructive or irreducibly ambiguous decision. Continue directly into the rewrite.

Implement the target architecture:

- keep PostgreSQL 16 locally;
- use ordinary Neon PostgreSQL in cloud through the standard SQLAlchemy/psycopg path;
- make Alembic the canonical migration system for both local and cloud;
- use a normal runtime `DATABASE_URL` and an optional direct `MIGRATION_DATABASE_URL` if needed for Neon/Alembic rather than a second database dialect;
- Cloud Run for the FastAPI API;
- GCS behind the existing `FileStore` boundary for private documents/artifacts;
- Firebase Hosting for the React SPA and same-origin `/api/**` routing to Cloud Run unless the live repo proves a simpler equivalent that preserves auth semantics;
- keep the current provider-neutral OIDC design, secure cookies, origin/CSRF checks and server-side authorization;
- Artifact Registry for container images;
- Secret Manager + Cloud Run service identity/ADC for cloud secrets and GCP access;
- preserve the existing durable Finance job rows/lease fencing; adapt cloud execution to bounded Cloud Run Job invocation where the existing hosted job workflow requires it rather than replacing the application job model;
- keep Finance authoritative for canonical data and deterministic calculations;
- keep Personal AI disabled/gated unless a separately reviewed transport/auth/data-handling contract already exists in the live repo.

For the database migration, **do a schema-parity review before deleting DSQL code**. Compare the canonical Alembic head with the independent DSQL migration plan and ensure every required table, constraint, index and backfill exists on the standard PostgreSQL path. Then retire DSQL engine/auth/migration/evidence code and tests that no longer serve the architecture. Preserve good database-only retry/idempotency/concurrency discipline; remove DSQL-only `OC001`, IAM-token, asynchronous-index, one-DDL-step and transaction-limit machinery unless a rule still has an independent correctness/performance reason.

For storage, preserve the existing local `PrivateFileStore` behavior and replace `S3FileStore` with a GCS implementation that retains the current privacy, content-addressing/key validation, size bounds, hash/length verification, duplicate/idempotency handling, stream cleanup and backend-mediated private preview semantics.

For Stage 4 infrastructure and operations, do not merely delete AWS code. Rewrite the current operational intent for GCP/Neon: replace App Runner/CloudFront/ECR/S3/DSQL/AWS IAM/budget Terraform with the smallest coherent Cloud Run/Firebase Hosting/Artifact Registry/GCS/Secret Manager/service-account setup; rewrite `tests/infra`; adapt the encrypted portable recovery flow to Neon + GCS; and simplify/replace the DSQL release-evidence gate with real Neon/GCP migration, reconnect/concurrency, HTTPS/auth, private-object and recovery evidence. Remove DSQL-only credential/token/index/migration-ledger cases.

Preserve historical truth in documentation. Current-facing docs and plans must stop teaching AWS/DSQL as the active production architecture, but dated AWS/DSQL release evidence should be clearly marked historical/superseded or otherwise preserved according to repo conventions rather than rewritten as if it never happened. Reconcile at least `AGENTS.md`, root/docs READMEs, architecture, roadmap, security/deployment, DSQL compatibility material, Stage 0–5 plans that encode active DSQL constraints, and Stage 4 plans/runbooks/release/cost material. Do **not** advance unrelated product features or convert partial/gated capabilities into completion claims.

Run a comprehensive validation/repair loop after the rewrite: the repo-defined aggregate quality gate, generated API checks, backend/frontend tests and builds, infrastructure tests, fresh PostgreSQL migration-to-head, representative populated upgrade paths, current finance workflows, storage tests, auth tests, job fencing/cancellation/retry tests, recovery tests, and browser journeys where their disposable DB gate is available. Run real Neon/GCP smoke/integration checks only if credentials/resources are available; otherwise mark them explicitly pending.

Before finishing, search the entire repo for stale active references to AWS/Amazon/Aurora/DSQL/`aurora_dsql`/boto/S3/CloudFront/App Runner/ECR/IAM ARN/`AWS_REGION`/`AURORA_DSQL_`/`PRIVATE_S3_`/`STATIC_ASSETS_BUCKET`/`OC001`. Every remaining match must be intentionally historical, migration commentary, or an unrelated source reference—not active code, current instructions, or future architecture.

Keep the migration focused: no unnecessary microservices, Kubernetes, Redis, Kafka, Celery, Pub/Sub, Cloud Tasks, new vector DB, Firebase Auth rewrite, or speculative provider integration. Do not overwrite unrelated user changes.

Finish with a concise migration report covering: the live baseline you found, major architecture changes, important modules preserved vs replaced, DSQL/AWS machinery retired, operational safeguards retained, validation performed and results, real Neon/GCP checks still pending, partial/gated product work intentionally left unchanged, intentional historical AWS references, and whether the repository now presents one coherent GCP/Neon architecture for continued development.
