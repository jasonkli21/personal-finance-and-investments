# Codex instructions — Personal Finance & Portfolio Intelligence

Stage 0–1 are delivered locally, Stage 2 is partial, Stage 3 is delivered locally, Stage 4 GCP/Neon tooling is prepared, and Stage 5 has an offline research baseline. Code, release records and the latest review describe delivery; plans are not evidence. Read this file and docs/README.md before changes.

## Read in order

1. docs/README.md — goals, status and document index.
2. docs/01-product-spec.md — requirements and non-goals.
3. docs/02-architecture.md — boundaries, schema and APIs.
4. docs/03-data-sources.md — source/freshness/licensing policy.
5. docs/04-ingestion-and-ai.md — processing and AI safeguards.
6. docs/05-roadmap.md — milestones and dependencies.
7. docs/06-security-and-deployment.md — privacy, GCP costs and recovery.
8. docs/07-postgres-neon.md — required database/migration/concurrency contract.

## Implementation posture

- Work only on the requested task; consult release evidence and the latest review. Do not build gated features speculatively.
- React/TypeScript/Vite, Tailwind, TanStack Query/Table; shadcn/ui and ECharts when justified. Python/FastAPI/Pydantic, SQLAlchemy 2, psycopg 3, Alembic. PostgreSQL 16 locally; ordinary Neon PostgreSQL in cloud. Docker Compose, uv and pnpm.
- One modular backend; no microservices, Kubernetes, Redis, separate vector DB or new queue without a demonstrated requirement.
- PostgreSQL/Neon owns structured finance data; PrivateFileStore locally and private GCS in cloud own originals/artifacts. Local/cloud are independent unless explicitly imported/exported.
- Alembic is the sole schema history. DATABASE_URL selects runtime; optional MIGRATION_DATABASE_URL selects a direct migration connection. Preserve app UUIDs, NUMERIC/Decimal, bounded pools/transactions and real Neon evidence before promotion.
- Cloud Run hosts API and bounded worker execution; Finance's durable DB jobs/lease fencing remain authoritative. Firebase Hosting serves the SPA with same-origin /api routing. Artifact Registry, Secret Manager and service identity/ADC supply images/secrets/GCP access.
- Preserve provider-neutral OIDC/PKCE, revocable database sessions, secure HttpOnly cookies, exact-origin/CSRF checks and server-side authorization. Firebase Hosting requires the tested __session transport; it does not select the identity provider.
- Finance owns canonical data, deterministic math, validation, review and UI. Reusable model access, extraction, retrieval and AI memory remain behind PersonalAIClient in personal-ai-system (ADR 0001). No deployed real-data calls without separately verified service/user authorization and data-handling review. PERSONAL_AI_ENABLED=true remains rejected.
- Keep providers behind adapters; local fixtures/manual imports/offline operation must remain viable.
- Use Decimal/NUMERIC for authoritative quantities, weights and money, with currency and valuation timestamps. Distinguish owned positions from derived ETF exposure; exposure is neither a tradable holding nor a tax lot.
- Retain source/as-of/quality/review status for every observation and inferred field. No real personal documents enter model providers by default.
- No order execution, trade recommendations, automatic tax filing, password scraping or claims of tax certainty.

## Workflow and hard gates

1. Locate roadmap acceptance criteria and state the smallest slice/modules.
2. Append migrations for persistent schema changes; never edit applied revisions. Test fresh and representative populated PostgreSQL upgrades; cloud evidence is separate.
3. Keep domain logic separate from endpoints/providers. External work completes outside DB-only retry callbacks; retry serialization/deadlock failures in bounded fresh transactions.
4. Use synthetic fixtures and negative tests for schema, bounded writes, idempotency, publication, reconciliation and concurrency as applicable. Flag real Neon/GCP checks pending if not run.
5. Refresh OpenAPI/generated TypeScript with repo commands; update behavior/architecture/source docs.
6. Report changed behavior, commands/tests and deviations.

Imports are staged/reviewed before canonical publication unless a specific trusted path was approved. Identical imports must not duplicate records. Preserve raw identifiers, unknown classes, zero/negative weights and unresolved securities; never force ETF weights to 100%. Reports disclose imported/estimated/stale/unavailable/derived values. Test direct + indirect decomposition + residual = original NAV within documented rounding tolerance; never add derived values to actual net worth.

Cloud finance routes and originals require authentication. Neon uses verified TLS; GCS is private and previews are backend mediated. Budgets are alerts, not hard spending caps. Keep unpublished staging revisions and atomic final publication; short row/byte bounds protect latency, memory and review usability. Shared generic research stays upstream; no speculative model or vector infrastructure here.

## Commands, evidence and history

README.md contains actual commands; docs/02-architecture.md distinguishes current layout from proposals. Keep tests in services/api/tests, apps/web/test, apps/web/e2e or tests/infra. Run pnpm check and available disposable PostgreSQL/browser gates. docs/gcp-neon-migration.md and ADR 0002 record the rearchitecture. docs/history/pre-gcp-neon preserves predecessor evidence; never use archived provider instructions for new work or rewrite dated evidence as a new run.

Provider prices/limits, source endpoints, bank coverage and model availability change. Verify official documentation before new integrations and record the date in docs/03-data-sources.md. Never promise permanently free cloud hosting.
