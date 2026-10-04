# ADR 0001 — Shared Personal AI, Finance authority

Accepted ownership decision, 2026-10-02; live transport remains deferred. Deployment choices are superseded by [ADR 0002](0002-gcp-neon.md), 2026-10-03. The original baseline inspection and dated provider context remain in [the historical ADR](../history/pre-gcp-neon/adr/0001-shared-personal-ai.md).

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

`PERSONAL_AI_ENABLED=false` is supported in host settings and Compose. True or malformed values fail startup. There is no HTTP adapter, base URL/timeout setting, trusted-local mode, research/memory/tool method or provider SDK. The handoff's minimum HTTP target is deliberately deferred: Stage 1 has no AI consumer, extraction transport is not agreed, and inventing endpoints/security configuration would be speculative. The fake demonstrates dependency substitution, not a functioning extraction feature or persistence safety test for an unimplemented workflow.

Run finance normally with the existing README commands; no upstream service is required. Run boundary tests with `uv run --directory services/api --locked pytest -q tests/test_personal_ai.py tests/test_config.py`; use `pnpm check` for the aggregate gate. A candidate rejected by the existing `PositionInput` validator remains a candidate, never a position write.

## Activation and security gaps

Before one real extraction feature in Stage 2:

1. Agree actual upstream capability, endpoint/version, source/evidence DTOs and bounded document transport; preserve finance private originals. Do not expose local paths over deployed APIs. Add HTTP timeout/size/redirect limits, safe error mapping and fake-HTTP tests.
2. Define consent, content minimization, provider data-use, storage/retention/deletion, logging and costs. Local trusted development requires explicit egress/storage rules; loopback and a flag do not prove safety or disable upstream cloud models.
3. For deployed private data, authenticate finance users and calling services; propagate only server-verified owner/scope and verify authorization upstream. Test absent/expired/wrong-audience credentials and wrong-owner denial. A fixed `local` owner or API key alone is insufficient.
4. Keep candidate normalization/evidence/arithmetic validation, duplicate detection, user review and bounded atomic publication in finance. External extraction completes outside transactions; save reusable output so OCC retry cannot repeat AI calls.

Current code enforces the disabled gate only; it does not implement or verify these future auth/transport/retention controls. Real-data deployment additionally requires the authenticated GCP/private-GCS and real-Neon gates in ADR 0002.

## Consequences and deferred sequence

This change preserves offline Stage 1 behavior and avoids duplicating infrastructure. Shared service outage must leave deterministic/manual finance workflows usable. Both apps retain their own deployability and data ownership.

Next, only when requested: integrate one reviewed extraction slice after the contract/security review; then shared research in Stage 5. Memory integration and deterministic read-only finance tools require separate concrete use cases and authorization contracts. Do not add mutation tools, a generic agent/plugin framework, speculative migrations or AI memory backfills now. No direct-provider code was removed because none exists.

Rejected alternatives: duplicate finance model/research/memory stack; moving deterministic arithmetic into prompts; sharing the AI database or replacing relational finance authority with Firestore; broad domain/repository rewrites; live adapters against guessed endpoints; treating AI candidates as approved records.
