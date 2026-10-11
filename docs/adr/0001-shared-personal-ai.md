# ADR 0001 — Shared Personal AI, Finance authority

Accepted ownership decision, 2026-10-02; the separately versioned read-only Finance context boundary was added on 2026-10-11. Deployment choices are superseded by [ADR 0002](0002-gcp-neon.md), 2026-10-03. The original baseline inspection and dated provider context remain in [the historical ADR](../history/pre-gcp-neon/adr/0001-shared-personal-ai.md).

## Decision

Finance remains a standalone product and authoritative owner of financial records, calculations, validation, import workflows, review, private originals, provenance and UI. Shared AI capabilities integrate through a small finance-side `PersonalAIClient` to independently owned `personal-ai-system`. No shared database/object store or imports of upstream internal Python modules.

Personal-AI owns model/provider routing, generic structured extraction/OCR runtime, research/search/retrieval/ranking, generic evidence lifecycle, attributable AI memory and general AI evaluation/orchestration. Finance keeps institution-specific deterministic templates, canonical schemas, field-evidence checks, source/as-of/quality metadata, hard constraints, arithmetic, user acceptance and persistence. Shared reusable entity resolution may propose matches; finance validates/reviews identifiers and issuer mappings. Model conclusions cannot become canonical positions, quotes, transactions or tax lots without finance's validated workflow.

Portfolio truth, AI preference memory and external evidence remain distinct. Finance may store saved research sessions, approved result/evidence snapshots, app settings and user-authored thesis notes. These do not require another model memory or generic index here.

## Current implementation seam

`services/api/app/integrations/personal_ai.py` provides:

- An async `PersonalAIClient.extract` protocol and narrow finance-owned request/candidate envelopes identifying source, schema and version. These are not the upstream wire contract or full statement schemas.
- Bounded text input without path/URL parameters. Candidate field payloads are untrusted; envelope/schema compliance alone is not financial validation.
- A disabled client with a stable safe error, and an explicit synthetic fake that checks source/schema/version and isolates returned payloads. No credentials, network, SQL access or publication methods.
- A disabled client installed at `app.state.personal_ai_client` as a future dependency boundary. Stage 1 routes/domain services do not consume it.

The Phase 28 `finance-context-read-v1` contract is a separate Finance-owned, read-only projection at `POST /v1/integrations/personal-ai/context`. It returns bounded selected account, current security/position, user-authored thesis, or registered research-fact context with typed semantic labels, source fingerprints, and permission-version dependencies. It does not reuse or widen `PersonalAIClient.extract`; it has no mutation, private-original, transaction, tax-lot, or publication operation. The endpoint and Personal AI adapter have independent default-off gates. See the [read contract](../personal-ai-context-read-v1.md) for exact bounds and fields.

`PERSONAL_AI_ENABLED=false` is supported in host settings and Compose. True or malformed values fail startup. The extraction client still has no HTTP adapter, base URL/timeout setting, trusted-local mode, research/memory/tool method or provider SDK. Its transport remains deferred because extraction has no reviewed consumer contract. The separate read API is gated by `FINANCE_CONTEXT_READ_ENABLED=false`; synthetic auth and projection tests do not establish deployed private-data readiness or enable any Finance workflow.

Run finance normally with the existing README commands; no upstream service is required. Run boundary tests with `uv run --directory services/api --locked pytest -q tests/test_personal_ai.py tests/test_config.py`; use `pnpm check` for the aggregate gate. A candidate rejected by the existing `PositionInput` validator remains a candidate, never a position write.

## Activation and security gaps

Before one real extraction feature in Stage 2:

1. Agree actual upstream capability, endpoint/version, source/evidence DTOs and bounded document transport; preserve finance private originals. Do not expose local paths over deployed APIs. Add HTTP timeout/size/redirect limits, safe error mapping and fake-HTTP tests.
2. Define consent, content minimization, provider data-use, storage/retention/deletion, logging and costs. Local trusted development requires explicit egress/storage rules; loopback and a flag do not prove safety or disable upstream cloud models.
3. For deployed private data, authenticate finance users and calling services; propagate only server-verified owner/scope and verify authorization upstream. Test absent/expired/wrong-audience credentials and wrong-owner denial. A fixed `local` owner or API key alone is insufficient.
4. Keep candidate normalization/evidence/arithmetic validation, duplicate detection, user review and bounded atomic publication in finance. External extraction completes outside transactions; save reusable output so OCC retry cannot repeat AI calls.

The extraction boundary enforces its disabled gate. The Phase 28 read endpoint implements separate audience-bound Google service and user ID-token checks, fixed configured-subject/principal binding, bounded JSON, no-store responses, and a read-only PostgreSQL transaction. These controls have synthetic tests only; real identity issuance, IAM/private service invocation, authorization against a deployed Finance owner mapping, provider data-use and retention, and live endpoint behavior remain unverified. Keep the read gate off until those deployment controls are accepted. Real-data deployment also requires the authenticated GCP/private-GCS and real-Neon gates in ADR 0002.

## Consequences and deferred sequence

This change preserves offline Stage 1 behavior and avoids duplicating infrastructure. Shared service outage must leave deterministic/manual finance workflows usable. Both apps retain their own deployability and data ownership.

The read-only contract is available for further integration work, but Phase 28 is incomplete while the accepted sidecar host contract, Phase 15 source/revocation prerequisites, Phase 21 workflow routing, and deployed identity/provider acceptance are open. The sidecar and any note/draft actions remain deferred; no authoritative Finance mutation is exposed. Extraction, shared research workflows, memory integration, and deterministic read-only tools still require their own concrete use cases and authorization contracts. Do not add mutation tools, a generic agent/plugin framework, speculative migrations or AI memory backfills. No direct-provider code was removed because none exists.

Rejected alternatives: duplicate finance model/research/memory stack; moving deterministic arithmetic into prompts; sharing the AI database or replacing relational finance authority with Firestore; broad domain/repository rewrites; live adapters against guessed endpoints; treating AI candidates as approved records.
