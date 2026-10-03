# Stage 5 implementation status

**Status:** S5.1.1 and the safe offline portion of S5.2.1 implemented; shared SEC/IR retrieval, AI synthesis, portfolio context, monitoring, live DSQL, and hosted promotion remain gated
**Updated:** 2026-10-03

This record separates finance-owned offline research workflow evidence from shared-service and provider capabilities that have not been integrated. No SEC data, personal portfolio context, or personal-AI service was requested or called during this implementation.

## Scope and dependency review

The implementation follows [the Stage 5 plan](stage-5-implementation-plan.md), [roadmap](05-roadmap.md), and [ADR 0001](adr/0001-shared-personal-ai.md). Before coding, the current `personal-ai-system` research API and contracts were inspected read-only. Its research surface is a session workflow (`POST /v1/research`, followed by a streaming `/run`) whose request contains a question, freshness mode, and idempotency key. Its owner is resolved from an authenticated user token. Finance's current `PersonalAIClient` still exposes extraction only; there is no agreed finance service identity, issuer/filing/date eligibility request, approved evidence excerpt transport, or owner propagation contract. The service's user-token session API is not treated as a finance service contract.

Finance therefore does not make a guessed HTTP call or start transmitting portfolio holdings, account/fund context, or thesis notes. Generic search, SEC/IR retrieval, evidence storage/indexing, and model synthesis remain upstream. The safe local baseline registers public SEC filing references and reported values only when a user enters them; every such item is explicitly `user_supplied_unverified`. No source contents are downloaded or represented as checked against SEC.

## S5.1 — Offline source and fact baseline

Added portable `research_documents` and `reported_facts` records with PostgreSQL Alembic revision `0016_stage5_research_sources` and an independent DSQL migration plan. The API accepts bounded SEC-hosted filing metadata and Decimal fact values. It preserves accession, CIK, filing and fiscal period, taxonomy/concept, unit/currency, raw and normalized values, source URL, registration time, and quality status. Repeated filing registration with identical metadata and repeated fact idempotency keys are stable; conflicting reuse is rejected. Reads are issuer/document scoped and bounded.

The SEC access/source check was reverified against official pages on 2026-10-03 and recorded in [the source register](03-data-sources.md#5-company-financials-and-regulatory-research--stage-5). `data.sec.gov` public JSON is documented as keyless and unavailable to browser CORS; SEC access guidance requires an identifying `User-Agent` and sets a 10 requests/second aggregate cap. This run made no SEC request. The fixture `fixtures/stage-5/synthetic-company-research.json` contains invented, non-resolving SEC-shaped identifiers and values only.

## S5.2 — Deterministic company view and research baseline

Added a bounded issuer view, manual filing/fact entry, sourced fact table, and explicit prior/current comparison. Comparison requires matching issuer, taxonomy, concept, unit, currency, period kind and fiscal period, consecutive fiscal years, and compatible date windows. Calculations use `Decimal`; missing values and non-positive denominators are explicit. Every source observation remains visible, including records that could be duplicate contexts or amendments; no observations are silently consolidated. The view shows filing dates, local registration dates, context references, original values, unverified quality, accession/form and original source link.

`research_runs` and `research_results` (revision `0017_stage5_research_runs`) freeze a deterministic, source-linked selection with a bounded result hash and idempotency key. This path contains no model-generated inferences and does not modify canonical positions, prices, transactions, or lots. Finance uses the upstream API inspection described above as a contract gate: no SEC/IR retrieval, shared evidence, private portfolio context, personal-AI request, or AI synthesis occurs. The UI remains available when all such services are disabled.

This completes only the safe manual/offline part of S5.2.1. Automated taxonomy normalization, amended-filing relationships, upstream search, and stale-cache behavior depend on source/retrieval contracts and remain unimplemented. S5.2.2 cited model synthesis remains gated on S5.3 privacy/context boundaries, S5.4 evidence contract/authorization, and explicit inference/data-handling approval.

### Remaining gates

- **S5.1.2 shared public observations:** not implemented. Requires an agreed service request/response contract with issuer and filing eligibility, retrievable provenance/excerpts, size/freshness limits, and service authorization. Upstream's current session/SSE API does not establish that contract.
- **S5.2.2 synthesized cited research:** not implemented. The only enabled path is the deterministic, user-entered source/fact baseline. No model output is emitted or treated as evidence.
- **S5.3 portfolio context and thesis/watchlists:** not implemented yet. No portfolio values or thesis text are transmitted to personal-AI.
- **S5.4 shared evidence retrieval:** not implemented yet. No finance index/search/database is added.
- **S5.5 monitoring:** not implemented. Stage 2 job delivery, restart, cleanup, and live DSQL lease acceptance remain partial/unverified; adding a second scheduler or notification path would bypass the dependency gate.
- **S5.6 evaluation/release:** pending. Real DSQL is unverified; hosted promotion remains blocked by Stage 4 evidence and authorization gates.

## S5.1 verification

- `UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage5_research.py tests/test_dsql_migrations.py` — **14 passed**. Coverage includes synthetic registration/listing, duplicate/conflict handling, URL/period/precision validation, DSQL plan structure, single-statement DDL and async indexes.
- Changed Stage 5 Python files passed Ruff lint and formatting checks.
- `pnpm api:generate` exported OpenAPI and regenerated `apps/web/src/api/schema.d.ts`; `pnpm api:check` passed. The bundled Node runtime and `/private/tmp` uv cache were needed in this shell.
- Local PostgreSQL was unavailable on port 55432, so Alembic migration runtime was not exercised on PostgreSQL. The migration is structurally represented in DSQL tests only; live Aurora DSQL remains unverified.
- No SEC, personal-AI, real-data, browser-hosted, or cloud call was made.

## S5.2 verification

- `UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage5_research.py tests/test_dsql_migrations.py` — **16 passed**. Synthetic coverage includes fiscal-period/unit incompatibility, missing/zero baseline behavior, source linkage, idempotency, frozen result integrity, and DSQL migration structure.
- Changed research modules passed mypy and Ruff. The frontend passed `pnpm --dir apps/web typecheck`, `pnpm api:check`, and `pnpm --dir apps/web build`; the build reports the existing large-chunk advisory.
- Migration 0017 is represented in the DSQL migration plan, but PostgreSQL runtime and real Aurora DSQL remain unverified because no local database/cluster is available.
