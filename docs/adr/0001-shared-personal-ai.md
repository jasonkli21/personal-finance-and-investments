# ADR 0001 — Shared personal-AI capabilities, finance authority

Status: Accepted architecture; live service integration deferred

Date: 2026-10-02

## Context and reconciliation

The [integration handoff](../../personal-finance-ai-integration-handoff/README.md) proposes incremental service integration. Current finance code/OpenAPI and [Stage 1 release evidence](../stage-1-release.md) are authoritative for delivered behavior; handoff examples are intended direction, not verified upstream APIs.

Reviewed baseline: `0874f21` (Stage 1.3), preceded by `f75e101` and `9053d1f`. The app has React/TypeScript/Vite, TanStack Query/Table, Tailwind, generated OpenAPI types, FastAPI/Pydantic, SQLAlchemy/Alembic, local PostgreSQL 16, a separate IAM/TLS DSQL engine/migration runner and private content-addressed files. Stage 1 includes reviewed position CSVs, generic/iShares fund CSVs and SPDR XLSX, manual/cached quotes, pure Decimal exposure and durable frozen report/drill-down/export. Live quote/issuer fetching, PDF/OCR, AI, research, memory, durable jobs, hosted authentication and S3 deployment are not delivered. shadcn/ui and ECharts remain optional planned additions, not installed components.

No existing AI code needs moving or replacing. Finance domain functions already separate calculations/publication from FastAPI and provider formats; they receive SQLAlchemy sessions directly. A new repository abstraction or domain/package split has no current justification.

| Component / conflict | Classification and resolution |
| --- | --- |
| `domains/portfolio.py`, `exposure.py`, `reports.py` | **Keep in finance:** exact arithmetic, source selection, frozen reports and reconciliation |
| `domains/imports.py`, `funds.py`, API contracts, private FileStore | **Keep in finance:** raw evidence, deterministic mapping/validation, duplicate detection, revision review and atomic bounded publication |
| `providers/quotes.py`, `fund_formats.py` | **Keep in finance:** non-AI financial observations and deterministic issuer parsing; uploads do not imply live issuer access |
| Planned `StructuredModelProvider`, Ollama/cloud adapters | **Replace planned ownership:** personal-AI owns reusable model/prompt/extraction infrastructure; finance consumes candidates |
| Planned `ResearchIndex`, search/ranking/evidence runtime | **Replace planned ownership:** shared research infrastructure lives upstream; finance retains necessary dated references/results and verifies finance semantics |
| AI preference memory versus finance data/settings/thesis | **Separate:** attributable cross-task preferences upstream; canonical holdings/transactions/lots, product settings and user thesis records in finance |
| Handoff `extract`/`research` endpoint examples | **Defer transport:** provisional contract; no finance document-extraction endpoint was found in the adjacent upstream API surface |
| Handoff's optional extraction review | **Resolve to repo gate:** financial candidates must pass finance validation and reviewed publication; no new trusted auto-commit path |
| “Not implemented” headers / restart Stage 0/1 prompt | **Correct stale status:** Stage 1 local MVP delivered; source live-fetch, remote CI and DSQL evidence remain separately qualified |
| Cloud/database choices | **Preserve:** local PG16, AWS production DSQL, private local/S3 originals, separate migrations and real-cluster promotion gate |

Read-only inspection of adjacent `personal-ai-system` on this date found provider/context/memory and local Phase 5 research code, with research session/run endpoints and SSE rather than the handoff's hypothetical JSON `research()` contract. Its README and `api/dependencies.py` still use a fixed `local` owner without authentication. That is inspection evidence, not a live deployment/security audit or a claim that generic finance extraction is available. No upstream files were changed.

## Decision

Finance remains a standalone product and authoritative owner of financial records, calculations, validation, import workflows, review, private originals, provenance and UI. Shared AI capabilities integrate through a small finance-side `PersonalAIClient` to independently owned `personal-ai-system`. No shared database/object store or imports of upstream internal Python modules.

Personal-AI owns model/provider routing, generic structured extraction/OCR runtime, research/search/retrieval/ranking, generic evidence lifecycle, attributable AI memory and general AI evaluation/orchestration. Finance keeps institution-specific deterministic templates, canonical schemas, field-evidence checks, source/as-of/quality metadata, hard constraints, arithmetic, user acceptance and persistence. Shared reusable entity resolution may propose matches; finance validates/reviews identifiers and issuer mappings. Model conclusions cannot become canonical positions, quotes, transactions or tax lots without finance's validated workflow.

Portfolio truth, AI preference memory and external evidence remain distinct. Finance may store saved research sessions, approved result/evidence snapshots, app settings and user-authored thesis notes. These do not require another model memory or generic index here.

The SQL/AWS design is unchanged. Cross-cloud authenticated HTTPS is possible when reviewed; it does not require shared VPCs, databases or moving finance to GCP/Firestore. No new persistent schema, migration, UI, finance endpoint or calculation change is justified for this reconciliation.

## Current implementation seam

`services/api/app/integrations/personal_ai.py` provides:

- An async `PersonalAIClient.extract` protocol and narrow finance-owned request/candidate envelopes identifying source, schema and version. These are not the upstream wire contract or full statement schemas.
- Bounded text input without path/URL parameters. Candidate field payloads are untrusted; envelope/schema compliance alone is not financial validation.
- A disabled client with a stable safe error, and an explicit synthetic fake that checks source/schema/version and isolates returned payloads. No credentials, network, SQL access or publication methods.
- A disabled client installed at `app.state.personal_ai_client` as a future dependency boundary. Stage 1 routes/domain services do not consume it.

`PERSONAL_AI_ENABLED=false` is supported in host settings and Compose. True or malformed values fail startup. There is no HTTP adapter, base URL/timeout setting, trusted-local mode, research/memory/tool method or provider SDK. The handoff's minimum HTTP target is deliberately deferred: Stage 1 has no AI consumer, extraction transport is not agreed, and inventing endpoints/security configuration would be speculative. The fake demonstrates dependency substitution, not a functioning extraction feature or persistence safety test for an unimplemented workflow.

Run finance normally with the existing README commands; no upstream service is required. Run boundary tests with `uv run --directory services/api --locked pytest -q tests/test_personal_ai.py tests/test_config.py`; use `pnpm check` for the aggregate gate. A candidate rejected by the existing `PositionInput` validator remains a candidate, never a position write.

## Activation and security gaps

Before one real extraction feature in Stage 2:

1. Agree actual upstream capability, endpoint/version, source/evidence DTOs and bounded document transport; preserve finance private originals. Do not expose local paths over deployed APIs. Add HTTP timeout/size/redirect limits, safe error mapping and fake-HTTP tests.
2. Define consent, content minimization, provider data-use, storage/retention/deletion, logging and costs. Local trusted development requires explicit egress/storage rules; loopback and a flag do not prove safety or disable upstream cloud models.
3. For deployed private data, authenticate finance users and calling services; propagate only server-verified owner/scope and verify authorization upstream. Test absent/expired/wrong-audience credentials and wrong-owner denial. A fixed `local` owner or API key alone is insufficient.
4. Keep candidate normalization/evidence/arithmetic validation, duplicate detection, user review and bounded atomic publication in finance. External extraction completes outside transactions; save reusable output so OCC retry cannot repeat AI calls.

Current code enforces the disabled gate only; it does not implement or verify these future auth/transport/retention controls. Real-data deployment additionally requires the existing authenticated AWS/private-S3 and real-DSQL gates. DSQL remains unverified.

## Consequences and deferred sequence

This change preserves offline Stage 1 behavior and avoids duplicating infrastructure. Shared service outage must leave deterministic/manual finance workflows usable. Both apps retain their own deployability and data ownership.

Next, only when requested: integrate one reviewed extraction slice after the contract/security review; then shared research in Stage 5. Memory integration and deterministic read-only finance tools require separate concrete use cases and authorization contracts. Do not add mutation tools, a generic agent/plugin framework, speculative migrations or AI memory backfills now. No direct-provider code was removed because none exists.

Rejected alternatives: duplicate finance model/research/memory stack; moving deterministic arithmetic into prompts; sharing the AI database or moving finance to Firestore/GCP; broad domain/repository rewrites; live adapters against guessed endpoints; treating AI candidates as approved records.
