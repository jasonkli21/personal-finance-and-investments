# Codex instructions — Personal Finance & Portfolio Intelligence

Read this file and [the docs router](docs/README.md) before changes. [Current state](docs/current-state.md) summarizes delivery and open gates; releases/reviews are evidence, plans are not. Read only task-relevant documents.

## Task routing

| Work | Route |
| --- | --- |
| Portfolio behavior, calculations, UI | [Portfolio and UI](docs/README.md#portfolio-and-ui) |
| Schema, persistence, migrations, concurrency | [Persistence and migrations](docs/README.md#persistence-and-migrations) |
| Providers, sources, imports | [Sources and imports](docs/README.md#sources-and-imports) |
| Personal AI boundary | [Personal AI](docs/README.md#personal-ai) |
| Authentication, privacy, deployment | [Security and deployment](docs/README.md#security-and-deployment) |
| Stage work or research | [Stage work and research](docs/README.md#stage-work-and-research) |
| Predecessor behavior | [History](docs/README.md#history) — only when needed |

## Durable finance rules

- Stack: React/TypeScript/Vite, Tailwind, TanStack Query/Table; shadcn/ui or ECharts when justified. API: Python/FastAPI/Pydantic, SQLAlchemy 2, psycopg 3, Alembic; Docker Compose, `uv`, `pnpm`.
- Keep one modular backend. Do not add microservices, Kubernetes, Redis, another database, vector store, or queue without a demonstrated requirement.
- PostgreSQL 16 (local) and Neon PostgreSQL (cloud) own structured data; `PrivateFileStore` and private GCS own originals/artifacts. Local/cloud stay independent without explicit import/export.
- Alembic is the only schema history. `DATABASE_URL` selects runtime; optional `MIGRATION_DATABASE_URL` selects direct migration. Preserve app UUIDs, `NUMERIC`/Decimal, bounded pools/transactions; require real Neon evidence before promotion.
- Cloud target: Cloud Run API/bounded worker, Firebase Hosting SPA with same-origin `/api`, private GCS, Artifact Registry and Secret Manager via service identity/ADC. Finance's durable DB jobs and lease fences remain authoritative.
- Preserve provider-neutral OIDC/PKCE, revocable DB sessions, secure HttpOnly cookies, exact-origin/CSRF checks, and server-side authorization. Firebase's tested `__session` transport does not choose the identity provider.
- Finance owns canonical data, deterministic math, validation, review, and UI. Reusable AI stays behind `PersonalAIClient` in `personal-ai-system` (ADR 0001). Real-data calls require verified authorization and data review; `PERSONAL_AI_ENABLED=true` remains rejected.
- Keep providers behind adapters. Manual imports, local fixtures, and offline operation must remain viable.
- Use Decimal/`NUMERIC` for authoritative quantities, weights, and money, with currency and valuation time. Owned positions are actual holdings; ETF look-through is derived exposure, never a tradable holding or tax lot.
- Retain source, as-of, quality, and review status for observations and inferred fields. Real personal documents do not enter model providers by default.
- Do not add order execution, trade recommendations, automatic tax filing, password scraping, or claims of tax certainty.

## Implementation and verification

- Find relevant roadmap acceptance and release/review evidence; implement the smallest requested slice. Do not build gated features speculatively.
- For schema changes, append a migration and never edit an applied revision. Validate fresh and representative populated PostgreSQL upgrades when relevant; cloud evidence is separate.
- Keep domain logic separate from endpoints/providers. Finish external work before DB-only retry callbacks; retry serialization/deadlock failures in bounded fresh transactions.
- Imports are staged and reviewed before canonical publication unless a specific trusted path is approved. Identical imports must not duplicate records. Preserve raw identifiers, unknown classes, zero/negative weights, and unresolved securities; never normalize ETF weights to 100% by force.
- Reports disclose imported, estimated, stale, unavailable, and derived values. Direct + indirect exposure + residual reconciles to original NAV within documented rounding tolerance; derived values never increase net worth.
- Use synthetic fixtures and negative tests for affected invariants. Tests live in `services/api/tests`, `apps/web/test`, `apps/web/e2e`, or `tests/infra`. Refresh OpenAPI/generated TypeScript and update affected docs; the root [README](README.md) lists commands.
- Cloud finance routes and originals require auth. Neon uses verified TLS; GCS is private with backend-mediated previews. Budgets are alerts, not caps. Keep unpublished staging and atomic publication; bound rows/bytes for latency, memory, and review usability.
- Verify official documentation before adding integrations or relying on mutable provider prices, limits, endpoints, bank coverage, or model availability. Record the verification date in `docs/03-data-sources.md`; never promise permanently free cloud hosting.
