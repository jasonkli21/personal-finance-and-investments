Historical snapshot, superseded by the current documentation router and status.

# Current implementation state

Updated 2026-10-13. This page is the concise current status summary. The linked release/review records contain the detailed, dated evidence; this page does not copy their test counts or turn plans into delivery claims.

## Delivered and available locally

- **Stage 0–1:** local foundation and portfolio/exposure MVP. Current evidence: [Stage 1 release](../../stage-1-release.md), [Stage 0 demo transcript](../../stage-0-demo-transcript.md), and [GCP/Neon migration validation](../../gcp-neon-migration.md).
- **Stage 3:** local history/performance, supplied tax-lot review, read-only hypothetical sale/allocation, and liquidity planning. Supplied remaining lot balances are not a complete dated lot ledger. Evidence: [Stage 3 release](../../stage-3-release.md).
- **Stage 5 baseline:** manual filing references/facts, deterministic comparisons, frozen portfolio contexts/results, thesis versions, manual watchlists, and provisional evidence validation. It makes no live retrieval or AI calls. Evidence: [Stage 5 release](../../stage-5-release.md) and [offline evaluation](../../stage-5-evaluation.md).

## Partial or gated

- **Stage 2 is partial.** Text-layer brokerage PDF previews, durable jobs, reviewed CSV/manual transactions, categories/splits/transfers, and source-labelled balances/summaries exist. OCR/shared extraction, account sync, recurring/month coverage, parsed-output reuse/cleanup, complete worker lifecycle, and benchmark acceptance remain open. See [Stage 2 release](../../stage-2-release.md) and [extraction gate](../../stage-2-ai-gate.md).
- **Stage 4 tooling is prepared, not deployed.** No GCP resources, Firebase Hosting deployment, or Neon branch is evidenced. Real Neon migration/reconnect/concurrency, hosted HTTPS/OIDC and private-object access, worker lifecycle, cost alerts, operations rehearsal, and cloud recovery remain unverified. See [Stage 4 release](../../stage-4-release.md) and [migration validation](../../gcp-neon-migration.md).
- **Personal AI remains disabled for Finance workflows.** The existing `PersonalAIClient.extract` candidate seam remains disabled and has no HTTP adapter. A separate read-only `finance-context-read-v1` projection is implemented behind `FINANCE_CONTEXT_READ_ENABLED=false` by default; its dual Google-token verification and principal binding have synthetic tests, but deployed identity, owner authorization, provider privacy, and live Finance API calls are unverified. The [Phase 28 verification record](../../phase-28-personal-ai-integration-evidence.md) preserves its historical test failure; the current cached-quote test now fixes valuation time and passes without changing production valuation behavior. No real personal documents or Finance data are sent to model providers.
- **Phase 30 discretionary budget export is implemented locally.** Finance owns one revisioned monthly amount/currency record per period. Shopping sharing is explicit and defaults off; the narrow export and its verify operation expose only amount, currency, and period for the Shopping purpose. The Personal AI adapter is separately gated by the Finance context flag. Its generated OpenAPI and TypeScript client now include the budget routes and schemas. The destination app has no accepted user-bound typed-task host, so Finance → Shopping is not available end to end. Migration 0019 is the local head; deployed identity, PostgreSQL migration, grant UX, and revocation acceptance remain open. See [Phase 30 budget export evidence](../../phase-30-discretionary-budget-evidence.md).
- **Stage 5 live capabilities remain gated.** Live retrieval/synthesis, verified source authenticity/semantic support, service authorization, list completeness, monitoring, and structured XBRL dimension/amendment equivalence are not delivered.

## Next scope and promotion boundary

No future product package is authorized by this status page. The [latest maintainability review](../../maintainability-review.md) recommends completing requested Stage 2 acceptance before relying on jobs for monitoring, and defining dated-lot and research comparison/list contracts when those areas are extended. Any work still needs a specific task scope and the relevant [roadmap package](../../05-roadmap.md).

Local/offline evidence does not establish Neon/GCP or real-data readiness. Promotion remains subject to the [security/deployment policy](../../06-security-and-deployment.md), [PostgreSQL/Neon evidence contract](../../07-postgres-neon.md), and [Stage 4 release gates](../../stage-4-release.md). Local and cloud data remain independent; no automatic synchronization is implemented.
