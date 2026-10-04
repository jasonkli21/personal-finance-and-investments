# Personal Finance & Portfolio Intelligence — Docs

Updated 2026-10-03. Stage 0–1 delivered locally; Stage 2 partial; Stage 3 delivered locally; Stage 4 GCP/Neon tooling prepared; Stage 5 offline/manual baseline. Real hosted deployment and Personal AI integration remain unverified/gated.

The private local-first app tracks actual positions separately from consolidated ETF look-through exposure, with dated sources, Decimal math, import review and reproducible reports. Later delivered local workflows include transactions, finance summaries, history, supplied tax lots and read-only hypothetical planning. It is decision support, without order execution or tax-certainty claims.

Local: PostgreSQL 16 + private filesystem. Cloud target: Neon PostgreSQL + GCS, Cloud Run API and bounded worker Job, Firebase Hosting same-origin SPA/API, Artifact Registry and Secret Manager/service identity. One PostgreSQL/Alembic contract serves both environments. No automatic local/cloud synchronization. See [ADR 0002](adr/0002-gcp-neon.md).

| Document | Purpose |
| --- | --- |
| [AGENTS.md](../AGENTS.md) | Implementation rules |
| [Product](01-product-spec.md) | Scope, users, journeys and acceptance |
| [Architecture](02-architecture.md) | Boundaries, schema, APIs and layout |
| [Sources](03-data-sources.md) | Provenance, freshness and licensing |
| [Ingestion/AI](04-ingestion-and-ai.md) | Deterministic validation and reviewed candidates |
| [Roadmap](05-roadmap.md) | Dependency-ordered work; plans do not prove delivery |
| [Security/deployment](06-security-and-deployment.md) | Auth, privacy, costs and portability |
| [PostgreSQL/Neon contract](07-postgres-neon.md) | Canonical migrations, TLS, retries and cloud tests |
| [Shared AI ownership](adr/0001-shared-personal-ai.md) | Finance authority and separately gated upstream capabilities |
| [Migration record](gcp-neon-migration.md) | Live baseline, schema parity, migration map and validation |
| [Maintainability review](maintainability-review.md) | Remaining product findings and review lineage |

| Stage | Plan | Current evidence |
| --- | --- | --- |
| 0 | [Foundation](stage-0-implementation-plan.md) | [Historical demo](stage-0-demo-transcript.md), migration validation |
| 1 | [Portfolio/exposure](stage-1-implementation-plan.md) | [Local MVP](stage-1-release.md) |
| 2 | [Ingestion/finance/jobs](stage-2-implementation-plan.md) | [Partial delivery](stage-2-release.md), [AI gate](stage-2-ai-gate.md) |
| 3 | [History/lots/planning](stage-3-implementation-plan.md) | [Local delivery](stage-3-release.md) |
| 4 | [GCP/Neon](stage-4-implementation-plan.md) | [Prepared tooling](stage-4-release.md), [costs](stage-4-cost-register.md), [recovery](stage-4-recovery-runbook.md), [operations](stage-4-operations-runbook.md) |
| 5 | [Research](stage-5-implementation-plan.md) | [Offline baseline](stage-5-release.md), [evaluation](stage-5-evaluation.md) |

Source-of-truth order: code/OpenAPI + release/review evidence for delivered behavior; product spec for scope; architecture and database contract for design; source policy for verified external facts; roadmap for sequencing; security policy takes precedence over convenience. Historical predecessor documentation is preserved under [history/pre-gcp-neon](history/pre-gcp-neon/README.md), clearly superseded. Archived test counts describe their original runs, not current acceptance.

Keep local/manual/offline workflows usable, preserve source evidence and unavailable data, and keep actual/derived values separate. Generic AI extraction/retrieval/model infrastructure belongs upstream; current Finance startup installs a disabled client and rejects activation. OCR, bank sync, live retrieval/synthesis/monitoring and broader Stage 2 acceptance remain separate work.
