# 02 — Target Architecture

## Goals

The target should make Finance look like a conventional PostgreSQL-backed domain application on GCP while preserving the strong local-first, deterministic-finance, privacy, review, concurrency, and recovery boundaries already present.

## Local architecture

Keep the local development architecture largely intact:

```text
Vite React SPA
      |
      | /api proxy
      v
FastAPI modular monolith
      |
      +---- SQLAlchemy/Alembic ---- PostgreSQL 16
      |
      +---- FileStore ------------ PrivateFileStore
      |
      +---- durable Job table ---- local worker
      |
      +---- PersonalAIClient ----- disabled by default
```

Do not make local development depend on GCP, Neon, Firebase, or model/provider credentials.

## Cloud architecture

```text
                    Firebase Hosting
                  SPA + same-origin /api
                           |
                           v
                    Cloud Run API
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
   Neon PostgreSQL        GCS        Secret Manager
   pooled app path     private files     secrets
   direct migration
       path
          |
          +------------------------------+
                                         |
                                         v
                                  Cloud Run Job
                              bounded worker execution

Artifact Registry -> API/worker image
Personal AI -> external service boundary, still gated unless separately enabled
```

## Database contract

### Canonical rule

There should be one application database contract: PostgreSQL.

```text
SQLAlchemy 2 + psycopg
          |
          +---- local PostgreSQL 16
          |
          +---- Neon PostgreSQL
```

Alembic becomes the canonical schema migration path for both local and cloud.

### App vs migration connections

Use normal PostgreSQL URLs. A practical cloud arrangement is:

- pooled Neon endpoint for Cloud Run application traffic;
- direct/non-pooled Neon endpoint for Alembic migration execution where appropriate.

Represent this with a simple `DATABASE_URL` plus an optional `MIGRATION_DATABASE_URL` rather than a second database dialect or IAM token generator. If the live repo can safely use one URL for both, keep it simpler.

### Existing correctness rules to preserve

Keep unless the audit proves they were purely DSQL cargo cult:

- application-generated UUIDs;
- `Decimal`/`NUMERIC` authoritative financial math;
- bounded imports and payloads;
- short transactions;
- provider/filesystem/model calls outside retryable DB units;
- idempotency keys and immutable/reviewed publication flows;
- conditional revisions / stale-write protection;
- durable job fencing and cancellation semantics.

Remove DSQL-only behavior such as `OC001`, IAM DB auth, DSQL token lifecycle, one-DDL-statement migration machinery, async-index polling, and the parallel DSQL schema ledger after parity is proven.

## Object storage

Preserve the existing `FileStore` interface:

```text
FileStore
  |
  +---- PrivateFileStore   (local)
  |
  +---- GCSFileStore       (cloud)
```

`GCSFileStore` should preserve the security/integrity contract of the current local/S3 implementations:

- private bucket only;
- no public statement URLs;
- bounded reads/writes;
- generated safe keys;
- hash/length verification;
- duplicate/idempotency checks;
- backend-mediated authenticated preview/download;
- default GCS encryption unless a concrete requirement justifies customer-managed keys.

## Frontend, edge routing, and auth

The existing provider-neutral OIDC implementation is valuable and should remain.

Use Firebase Hosting primarily for:

- static React build hosting;
- SPA fallback;
- same-origin routing of `/api/**` to Cloud Run.

Preserve:

- exact HTTPS public origin;
- auth callback path semantics;
- secure `HttpOnly` cookies;
- origin/CSRF checks;
- private route gating;
- backend authorization as the security boundary.

Do not rely on obscuring the Cloud Run service URL for authorization. Configure ingress/IAM/routing appropriately, but backend auth remains mandatory.

## Background work

The current durable-job model is part of Finance behavior, not an AWS implementation detail.

Target model:

```text
API enqueues durable Job row
        |
        +--> local: existing in-process/polling worker
        |
        +--> cloud: trigger bounded Cloud Run Job execution
                         |
                         v
                claim DB job with existing fence
                process outside DB transaction
                persist progress/result safely
                exit when bounded work is done
```

Prefer adapting `app/jobs/runner.py` to expose a one-shot/bounded processor over inventing another queue/state machine. Preserve the current incomplete/gated status of Stage 2 acceptance work unless the migration itself explicitly closes a requirement with evidence.

## Infrastructure and IaC

Replace the existing AWS Terraform target rather than abandoning infrastructure-as-code discipline.

Expected GCP resources/concepts:

- Cloud Run API service;
- Cloud Run Job if required by existing job workflows;
- Artifact Registry repository;
- GCS private object bucket;
- Secret Manager secrets/references;
- dedicated Cloud Run service account with least privilege;
- Firebase Hosting site/configuration and Cloud Run rewrite, using Terraform and/or Firebase config/CLI where each is simplest and reproducible;
- budget/alert documentation appropriate to GCP and the external Neon account.

Neon itself may be managed outside Terraform if that keeps the personal project simpler. Do not add a third-party Terraform provider solely for aesthetic symmetry unless it materially helps reproducibility.

## Recovery and release

Preserve the current encrypted portable archive concept. Rewrite cloud-specific recovery checks for Neon + GCS.

The existing release gate/evidence machinery should be simplified, not blindly retained or deleted. Keep useful concepts:

- source/build/schema fingerprints;
- clean-tree or exact-source binding where appropriate;
- fail closed on missing required evidence;
- migration verification;
- authenticated HTTPS smoke test;
- private-object access controls;
- recovery drill evidence.

Delete DSQL-specific 16-minute IAM-token, async-index, special migration-ledger, and DSQL cluster identity requirements.

## Personal AI

No architectural change is required merely because Finance moves to GCP.

Continue to enforce:

```text
Finance owns authoritative data + deterministic logic
Personal AI owns reusable extraction/research/model capabilities
```

Do not turn `PERSONAL_AI_ENABLED` on as part of this migration. If the live repo still lacks an agreed service auth/owner/data-handling contract, preserve the fail-closed gate.
