# Codex instructions — Personal Finance & Portfolio Intelligence

This repository implements a local-first personal-finance and investment-analysis application through **Stage 1**. Existing code and release evidence describe delivered behavior; future-stage documents remain plans. The documents in `docs/` are the current requirements; do not assume every described capability is implemented. Read this file and `docs/README.md` before making changes.

## Read in this order

1. `docs/README.md` — project goals, current phase, document index.
2. `docs/01-product-spec.md` — users, requirements, acceptance criteria, non-goals.
3. `docs/02-architecture.md` — technical decisions, domain boundaries, data model, APIs.
4. `docs/03-data-sources.md` — source priority, freshness, costs, licensing constraints.
5. `docs/04-ingestion-and-ai.md` — document processing, LLM boundaries, safeguards.
6. `docs/05-roadmap.md` — staged milestones and dependency-ordered work.
7. `docs/06-security-and-deployment.md` — privacy, portability, AWS cost controls.
8. `docs/07-aurora-dsql-compatibility.md` — **required** DSQL dialect, migration, transaction, IAM, jobs, search and test contract.

## Default implementation posture

- Work **only on the requested stage/task**. Stage 0 and Stage 1 are delivered; consult release evidence before starting new work. Do not build future stages speculatively.
- Stack: React + TypeScript + Vite; Tailwind + shadcn/ui; TanStack Query/Table; ECharts; Python + FastAPI + Pydantic; SQLAlchemy 2 + Alembic + psycopg 3; **PostgreSQL 16 locally, Amazon Aurora DSQL in production**; Docker Compose; `uv` + `pnpm`.
- Build a modular **single deployable backend**. Background jobs can share the backend codebase; no microservices, Kubernetes, Redis, or separate vector database in the MVP.
- Local PostgreSQL or production Aurora DSQL is the source of truth for structured financial data in its respective environment. The local filesystem/private S3 holds original files. Local and production are independent unless the user explicitly imports/exports data.
- **DSQL compatibility is a design constraint from Stage 0:** app-generated UUIDs, portable relational schema, independent DSQL dialect/connection/migration config, short bounded writes, and real DSQL integration tests before production promotion. A local PostgreSQL test alone is not sufficient.
- Finance owns canonical data, deterministic validation/calculations, workflows and UI. Reusable model access, generic extraction, research/search, evidence retrieval and AI memory belong in `personal-ai-system` behind `PersonalAIClient`; do not recreate that infrastructure here. See `docs/adr/0001-shared-personal-ai.md`. Deployed real-data calls remain blocked pending verified user/service authorization and data-handling review.
- Keep all external providers behind interfaces/adapters. Local fixtures, manual imports, and offline operation must remain viable.
- Prefer `Decimal` and portable SQL `NUMERIC` for quantities, money, and weights. Never use binary floats for authoritative financial arithmetic; provide currency and valuation timestamps.
- Distinguish **actual owned positions** from **derived ETF look-through exposure**. The latter is not a tradable holding or a tax lot.
- Every imported row, price, ETF holding snapshot, and inferred field must retain its source, as-of timestamp, and quality/review status.
- No AI provider receives real personal financial documents by default. Local parsing first; cloud inference requires explicit opt-in and data-handling review.
- No order execution, trade recommendations, automatic tax filing, password scraping, or claims of tax-certainty.

## Engineering workflow for each task

1. Locate the relevant stage and acceptance criteria in `docs/05-roadmap.md`.
2. State the smallest vertical slice and affected domain modules.
3. Add or update database migrations for persistent schema changes; never edit an existing applied migration. Test the **DSQL migration path**, which requires separate DDL/DML transactions and only one DDL statement per transaction; asynchronous indexes must reach ready state before dependent steps.
4. Implement domain logic separately from FastAPI endpoints and provider clients.
5. Add realistic but **synthetic** test fixtures and tests, including negative cases, bounded batch writes, idempotency and retry behavior where applicable; flag DSQL-required tests as unverified unless executed on a real cluster.
6. Expose backend contracts through OpenAPI; generate/refresh the TypeScript client rather than hand-maintaining duplicate schemas.
7. Update the relevant docs if behavior, architecture, or source assumptions change.
8. At completion, report what changed, how to run it, tests executed, and deviations from the docs.

## Hard correctness gates

- Imports are staged/reviewed before they affect canonical positions or transactions, unless the specific trusted import path has been explicitly approved.
- Reimporting an identical statement or holdings snapshot must not duplicate assets or transactions.
- Preserve raw source values, including identifiers, unrecognized asset classes, zero/negative weights, and unresolved securities. Do not silently discard discrepancies or normalize ETF weights to 100%.
- A report must show whether numbers are imported, estimated, stale, unavailable, or derived.
- Test reconciliation: `direct assets + indirect look-through decomposition + residual = original portfolio value` within documented rounding tolerances, **without** adding look-through values to actual net worth.
- Cloud app routes and raw statements must not be publicly exposed without authentication. DSQL uses IAM+TLS; PrivateLink can add fees. Budgets/alerts are not hard spending caps.
- Avoid a production dependency on `pgvector`, assumed `tsvector`/extension support, PostgreSQL-specific triggers/procedures, or `FOR UPDATE SKIP LOCKED`. Use the shared personal-AI service for generic research retrieval and a finance worker/job interface (SQS or a tested DSQL optimistic lease in cloud).
- Batch large imports with unpublished staging revisions; make publication atomic and retry OCC failures **without re-running external API/AI calls**. See `docs/07-aurora-dsql-compatibility.md`.

## Commands and repository layout

The current layout and future additions are distinguished in `docs/02-architecture.md`; actual commands and delivery evidence are in `README.md` and `docs/stage-1-release.md`. Proposed additions are not evidence that scripts or directories already exist. When bootstrapping, favor standard tooling and document the actual commands after implementation.

## Decisions needing evidence before changing

Free-tier limits, issuer holdings endpoints and export formats, bank coverage, AWS services/prices, and model availability change. Check current official provider documentation before implementing a new integration and update `docs/03-data-sources.md` with a verification date. DSQL has an ongoing allowance of 100,000 DPUs + 1 GB-month of storage (checked 2026-09-25), but excess DSQL usage and the remaining AWS stack can incur charges. Never hard-code a claim of permanently free cloud hosting.