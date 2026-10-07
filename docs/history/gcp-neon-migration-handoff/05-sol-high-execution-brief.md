# 05 — Sol High Execution Brief

## Objective

Rearchitect `personal-finance-and-investments` from AWS/Aurora DSQL to GCP + Neon in one coherent pass while preserving the existing local-first finance application, security/correctness boundaries, and honest release status.

## Repo-informed facts to verify, not blindly assume

A targeted review of public `main` at `4e5f3e3` found:

- ordinary PostgreSQL 16 local runtime with SQLAlchemy/Alembic;
- 18 Alembic revisions and a large separate DSQL migration implementation;
- production config hard-wired to DSQL + S3 + AWS settings;
- clean `DatabaseEngineFactory` and `FileStore` seams worth preserving;
- provider-neutral OIDC auth already implemented;
- database-backed durable jobs + local PDF worker;
- substantial Stage 4 Terraform/recovery/release tooling for App Runner, CloudFront, ECR, S3, DSQL, IAM and budgets, but no AWS resources provisioned in the reviewed snapshot;
- Stage 5 offline/manual research with Personal AI/retrieval still disabled/gated;
- Stage 2 explicitly partial.

Read the live repo and release evidence first because these details may have changed.

## Core rewrite

- PostgreSQL/Alembic becomes the single DB path; Neon is production PostgreSQL.
- Retire the parallel DSQL engine/migration/evidence stack after parity verification.
- Keep portable transaction/idempotency/concurrency safeguards; remove DSQL-only `OC001`, IAM token, DDL/index machinery and transaction constraints.
- Keep `FileStore`; replace S3 with GCS.
- Keep OIDC; replace CloudFront/App Runner/ECR routing/runtime with Firebase Hosting + Cloud Run + Artifact Registry.
- Keep DB-backed job state and fencing; adapt cloud execution to bounded Cloud Run Jobs if hosted PDF jobs are in scope.
- Rewrite Terraform/infrastructure tests instead of deleting IaC discipline.
- Adapt encrypted recovery and fail-closed release evidence to Neon/GCP.
- Do not activate Personal AI or complete unrelated product stages.

## Execution order

1. Read `AGENTS.md`, docs index, release records, maintainability review, and this handoff.
2. Run baseline validation where practical.
3. Build a concise preserve/generalize/replace/retire map.
4. Record the new architecture decision.
5. Rewrite DB config/engine/migrations/transactions.
6. Rewrite storage.
7. Preserve auth while replacing edge/runtime routing.
8. Port background execution.
9. Rewrite Terraform/deployment/cost controls.
10. Rewrite recovery/release evidence.
11. Reconcile current docs and future plans.
12. Run full regression/repair loop.
13. Search for stale AWS/DSQL assumptions.
14. Produce final migration report.

## Guardrails

- Live repo is authoritative.
- Do not edit applied historical Alembic migrations just to make them prettier or more cloud-generic.
- Do not delete strong correctness/security behavior merely because it was originally motivated by DSQL.
- Do not preserve DSQL-specific complexity merely because much code was written for it.
- Do not invent dual-write/cutover machinery if no AWS deployment/data exists.
- Do not switch identity architecture to Firebase Auth by default.
- Do not add Pub/Sub/Cloud Tasks/Redis/Celery/Kubernetes without a demonstrated requirement.
- Do not treat plans as completion evidence.
- Do not claim real Neon/GCP validation when credentials/resources are unavailable.
