# Current implementation state

Updated 2026-10-07. This page is the concise current status summary. The linked release/review records contain the detailed, dated evidence; this page does not copy their test counts or turn plans into delivery claims.

## Delivered and available locally

- **Stage 0–1:** local foundation and portfolio/exposure MVP. Current evidence: [Stage 1 release](stage-1-release.md), [Stage 0 demo transcript](stage-0-demo-transcript.md), and [GCP/Neon migration validation](gcp-neon-migration.md).
- **Stage 3:** local history/performance, supplied tax-lot review, read-only hypothetical sale/allocation, and liquidity planning. Supplied remaining lot balances are not a complete dated lot ledger. Evidence: [Stage 3 release](stage-3-release.md).
- **Stage 5 baseline:** manual filing references/facts, deterministic comparisons, frozen portfolio contexts/results, thesis versions, manual watchlists, and provisional evidence validation. It makes no live retrieval or AI calls. Evidence: [Stage 5 release](stage-5-release.md) and [offline evaluation](stage-5-evaluation.md).

## Partial or gated

- **Stage 2 is partial.** Text-layer brokerage PDF previews, durable jobs, reviewed CSV/manual transactions, categories/splits/transfers, and source-labelled balances/summaries exist. OCR/shared extraction, account sync, recurring/month coverage, parsed-output reuse/cleanup, complete worker lifecycle, and benchmark acceptance remain open. See [Stage 2 release](stage-2-release.md) and [extraction gate](stage-2-ai-gate.md).
- **Stage 4 tooling is prepared, not deployed.** No GCP resources, Firebase Hosting deployment, or Neon branch is evidenced. Real Neon migration/reconnect/concurrency, hosted HTTPS/OIDC and private-object access, worker lifecycle, cost alerts, operations rehearsal, and cloud recovery remain unverified. See [Stage 4 release](stage-4-release.md) and [migration validation](gcp-neon-migration.md).
- **Personal AI remains disabled.** There is no Finance transport or verified service/user authorization and owner propagation. `PERSONAL_AI_ENABLED=true` is rejected. No real personal documents are sent to model providers.
- **Stage 5 live capabilities remain gated.** Live retrieval/synthesis, verified source authenticity/semantic support, service authorization, list completeness, monitoring, and structured XBRL dimension/amendment equivalence are not delivered.

## Next scope and promotion boundary

No future product package is authorized by this status page. The [latest maintainability review](maintainability-review.md) recommends completing requested Stage 2 acceptance before relying on jobs for monitoring, and defining dated-lot and research comparison/list contracts when those areas are extended. Any work still needs a specific task scope and the relevant [roadmap package](05-roadmap.md).

Local/offline evidence does not establish Neon/GCP or real-data readiness. Promotion remains subject to the [security/deployment policy](06-security-and-deployment.md), [PostgreSQL/Neon evidence contract](07-postgres-neon.md), and [Stage 4 release gates](stage-4-release.md). Local and cloud data remain independent; no automatic synchronization is implemented.
