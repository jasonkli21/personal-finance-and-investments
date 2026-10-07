# Historical migration handoff

This one-time package guided the 2026-10-03 AWS/Aurora DSQL to GCP/Neon repository rearchitecture. The code/documentation migration is complete in this checkout; cloud deployment remains unverified. The package is retained as historical planning context, not current implementation guidance. Use the [current documentation router](../../README.md), [current state](../../current-state.md), [ADR 0002](../../adr/0002-gcp-neon.md), and [migration record](../../gcp-neon-migration.md) for current decisions and evidence.

# Finance Project: AWS/Aurora DSQL -> GCP/Neon Migration Handoff

## Purpose

This package guides a one-session rearchitecture of `personal-finance-and-investments` from its current AWS/Aurora DSQL production target to GCP + Neon while preserving the working local finance application and its existing correctness/security boundaries.

This revision is informed by a targeted read of public `main` at commit `4e5f3e330a401a4df2f75781689a42300868bdbb` (2026-10-03). The live checkout at execution time remains authoritative.

## Repo-informed orientation

The current repository is not an early scaffold. It already contains substantial product code and substantial AWS-specific deployment/release machinery:

- React/TypeScript/Vite frontend plus one FastAPI backend.
- SQLAlchemy 2 + Alembic with PostgreSQL 16 as the local runtime.
- 18 Alembic revisions through Stage 5-era schema.
- A separate Aurora DSQL engine path and a large independent DSQL migration plan (`app/db/dsql_migrations.py`).
- Production configuration that currently fails closed unless Aurora DSQL, AWS Region, S3, HTTPS auth, and a migration role are configured.
- A useful `FileStore` abstraction with local storage plus an S3 implementation.
- Provider-neutral OIDC authentication/session logic already implemented locally.
- Durable database-backed jobs and a local optimistic-lease PDF worker.
- Terraform for DSQL, S3, CloudFront, ECR, App Runner, IAM, budgets, and related Stage 4 controls.
- Encrypted portable recovery, deployment/release evidence tooling, and operations runbooks.
- A disabled `PersonalAIClient` extraction boundary plus a provisional research-evidence boundary; no live Personal AI transport is currently enabled.
- Current release evidence distinguishes local/offline delivery from incomplete or unverified cloud/provider work. Do not infer completion from stage numbers alone.

Important current-state orientation from the repo docs: Stage 2 is explicitly partial; Stage 4 is largely prepared deployment/recovery/release tooling with no AWS resources provisioned; Stage 5 is an offline research baseline with live retrieval/AI/monitoring gated. Sol must still verify these statements against the live checkout before editing.

## Recommended execution model

- **Model:** Sol
- **Reasoning:** High
- **Execution style:** one coherent repo-wide session
- **Delegation:** keep the core audit, architecture rewrite, implementation, validation, and documentation in the same Sol context
- **Escalation:** move higher only if the live audit exposes conflicts or coupling materially beyond this snapshot

This migration is consistency-heavy. Splitting database, storage, infrastructure, release tooling, and docs across independent agents increases the chance of leaving incompatible assumptions behind.

## Target state

### Local

```text
React + TypeScript + Vite
          |
          v
FastAPI + Python
          |
          v
SQLAlchemy + Alembic
          |
          v
PostgreSQL 16

PrivateFileStore
DB-backed durable jobs + local worker
Personal AI disabled unless separately authorized
```

### Cloud

```text
Firebase Hosting
  static SPA + same-origin /api routing
          |
          v
Cloud Run API
          |
          +------> Neon PostgreSQL
          |
          +------> GCS private objects
          |
          +------> Secret Manager
          |
          +------> Personal AI API (still gated unless contract/security work exists)

Artifact Registry -> Cloud Run image
Cloud Run Job(s) -> bounded background execution where the existing durable-job workflow requires it
```

## Architectural decisions

1. **Keep the modular monolith.** Do not introduce microservices, Redis, Kafka, Celery, Kubernetes, or a new queue unless the live code proves a current requirement.
2. **Make ordinary PostgreSQL the single database contract.** Local PostgreSQL and Neon should share SQLAlchemy/Alembic semantics. The independent DSQL migration system should be retired only after schema-parity review.
3. **Preserve the good existing boundaries.** `DatabaseEngineFactory`, `FileStore`, domain/API separation, provider interfaces, deterministic finance calculations, and the Personal AI boundary are useful structure; rewrite implementations rather than flattening them.
4. **Replace S3 with GCS behind `FileStore`.** Preserve local private storage behavior and content-integrity/size/security checks.
5. **Replace AWS hosting with GCP while preserving the current auth model.** OIDC is provider-neutral; do not switch to Firebase Auth merely because Firebase Hosting is used.
6. **Preserve same-origin auth/API behavior.** The current app uses origin checks, secure cookies, and an `/api` edge path. Firebase Hosting/Cloud Run routing should preserve those semantics unless a simpler equivalent is proven.
7. **Preserve durable job state.** The existing database job/lease/fencing model is real application behavior. Cloud Run Jobs should adapt to that model rather than replacing it with an unrelated job system.
8. **Preserve recovery and release discipline.** Replace AWS/DSQL-specific recovery/evidence gates with Neon/GCP equivalents; do not simply delete Stage 4 operational safeguards.
9. **Do not activate Personal AI as part of the cloud migration.** Keep finance authoritative. Existing AI/research gates remain gates unless separately implemented and authorized.
10. **Do not rewrite historical evidence as if it never happened.** Current-facing docs/plans must point to GCP/Neon, but dated AWS/DSQL release evidence should be marked historical/superseded or moved/linked appropriately rather than falsified.

## Documents

1. `01-current-state-audit-and-scope.md` — repo-informed audit checklist and rewrite scope
2. `02-target-architecture.md` — concrete target architecture mapped to existing modules
3. `03-migration-execution-plan.md` — ordered end-to-end rewrite plan
4. `04-validation-and-acceptance.md` — regression, cloud, and stale-provider gates
5. `05-sol-high-execution-brief.md` — condensed operating instructions
6. `06-sol-high-prompt.md` — copy/paste prompt for the Sol High Codex session

## Execution principle

```text
Read live repo + run baseline
        |
        v
Confirm actual capability/status map
        |
        v
Map concrete AWS/DSQL coupling
        |
        v
Rewrite DB/storage/runtime/infra/release tooling
        |
        v
Reconcile current docs and future plans
        |
        v
Run full regression + Neon/GCP checks when credentials exist
        |
        v
Search for stale AWS/DSQL assumptions
        |
        v
Produce migration report
```

The audit and rewrite belong in the same session. Do not stop after producing an audit unless an actually destructive or irreducibly ambiguous decision requires user input.
