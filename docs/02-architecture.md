# Technical architecture and data model

**Status:** Proposed, implementation-independent | **Updated:** 2026-09-25

## 1. Architecture decision

**Modular monolith with two supported SQL targets: PostgreSQL 16 locally and Aurora DSQL in production.** A React/Vite SPA calls a Python/FastAPI REST API. Python background tasks share the same domain and provider adapters. A configurable SQLAlchemy engine and DSQL-aware migration path switch database infrastructure without duplicating business logic. Local and cloud data do not automatically sync. Keep it SQL-first; bounded `JSONB` can hold raw provider metadata in both targets. See [`07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md) for the production compatibility contract.

```text
React + TypeScript SPA (Vite)
  | REST/JSON, OpenAPI-generated TypeScript client
FastAPI application
  |-- accounts / securities / positions
  |-- market_data / etf_holdings / exposure
  |-- imports / spending / taxes / research (as stages unlock)
  |-- provider interfaces: quotes, fund holdings, account sync, AI, search
  |-- jobs service: enqueue, run, status, retries
  +---- DatabaseEngine: local PostgreSQL 16 OR production Aurora DSQL
  +---- FileStore interface -> local files or private S3
Python worker/scheduler -> same domain services and interfaces
```

**No** default Redis, Kubernetes, microservices, separate vector DB, or model-hosting infrastructure. For Stage 0–1, CLI-triggered/scheduled refreshes suffice. Introduce a `JobStore`/`JobRunner` interface in Stage 2: local single-worker polling is fine; cloud can use SQS or a tested DSQL-compatible optimistic lease. Do not assume PostgreSQL row-locking queue recipes transfer unchanged.

## 2. Technology decisions

| Responsibility | Proposed choice | Notes |
| --- | --- | --- |
| Web client | React + TypeScript + Vite | Static SPA; no SSR requirement |
| UI | Tailwind CSS + shadcn/ui | Accessible, composable dashboard |
| Async API state / grids | TanStack Query / TanStack Table | Server-driven caching, sorting, dense holdings grids |
| Charts | Apache ECharts | Allocation, trend, treemap/overlap; accessible table alternatives |
| Routing / forms | React Router; React Hook Form + Zod (optional) | Avoid duplicate canonical backend validation |
| API | Python 3.12+ + FastAPI + Pydantic v2 | Pin/test exact versions at scaffold time |
| Persistence | PostgreSQL 16 locally; Aurora DSQL in production; SQLAlchemy 2, psycopg 3, Alembic | Application UUID PKs, portable models, DSQL-specific engine/IAM and migration logic |
| Finance math | Python `Decimal`; SQL `NUMERIC` on both targets | Never use floats for authoritative money/weights |
| Data transforms | stdlib/SQL first; pandas/Polars later if useful | SQL should answer core look-through queries |
| Downloads/parsing | httpx; csv; PyMuPDF subject to license or pypdf; Docling later | Check site Terms/robots for issuer adapters |
| AI | Ollama local + Pydantic schema; optional Groq provider | **Not part of Stage 1's critical path** |
| Storage | Local private directory -> S3 via `FileStore` | Raw documents never in public SPA asset bucket |
| Jobs | CLI/cron -> abstract `JobStore` and worker | Local PostgreSQL polling; DSQL-verified lease or SQS in production; at-least-once/idempotent |
| Tooling | `uv`, `pnpm`, Docker Compose | Use lockfiles and `.env.example` |
| Tests | pytest + real PG 16, gated real DSQL integration suite, Vitest, Playwright | DSQL tests required for promotion; local suite remains offline |
| CI/CD | GitHub Actions when scaffolded | Local lint, typecheck, tests before cloud deploy |

**Client API typing:** generate the TypeScript HTTP client from FastAPI's OpenAPI schema using `openapi-typescript` or Orval. Avoid hand-written duplicate request/response interfaces when the backend contract can generate them.

**Dual-engine execution:** configure the database at boot (`DATABASE_BACKEND=postgres|aurora_dsql`) through `DatabaseEngineFactory`; create a separate DSQL SQLAlchemy engine with the official connector, scoped IAM token-on-connect and TLS hostname verification. DSQL rejects `DATABASE_URL`; the migration identity is configured separately from the app role. Never reuse a stale auth token for new pooled connections. PostgreSQL uses Alembic; DSQL uses the versioned runner with separate DDL/DML transactions, one DDL statement per transaction and asynchronous index readiness. Domain methods should not branch on backend in ordinary business code.

## 3. Proposed repository layout

```text
/
├── AGENTS.md
├── README.md                      # Created during Stage 0
├── .env.example                   # Placeholder names only; never actual keys
├── compose.yaml
├── docs/                         # These handoff documents
├── apps/
│   └── web/                       # Vite React TypeScript app
├── services/
│   └── api/
│       ├── pyproject.toml
│       ├── alembic/
│       ├── app/
│       │   ├── main.py
│       │   ├── config.py
│       │   ├── api/               # Routes and generated OpenAPI contracts
│       │   ├── db/                # DatabaseEngineFactory, sessions, local/DSQL migration paths
│       │   ├── domains/
│       │   │   ├── accounts/
│       │   │   ├── securities/
│       │   │   ├── portfolio/
│       │   │   ├── funds/
│       │   │   ├── prices/
│       │   │   ├── ingestion/      # Stage 2
│       │   │   ├── spending/       # Stage 2
│       │   │   ├── tax/            # Stage 3
│       │   │   └── research/       # Stage 5
│       │   ├── providers/          # External adapters + local fixtures
│       │   ├── jobs/              # Backend-neutral job interface
│       │   └── storage/
│       └── tests/
├── fixtures/                      # Synthetic data only
└── infra/                         # Added in Stage 4
```

This is a desired layout rather than a mandate to precreate empty domains. Create directories as each feature is implemented; keep meaningful boundaries between API handlers, domain calculations, ORM mappings, and provider-specific code.

## 4. Conceptual relational schema

The following is a **logical design**; create exact migrations incrementally. Include `created_at`, `updated_at` and owner/scope where relevant. Favor immutable dated snapshots over in-place mutation of external observations.

| Table / concept | Representative fields and invariants |
| --- | --- |
| `accounts` | `id`, name, account_type, base_currency, active, source_type; account identity is independent of brokerage |
| `issuers` | `id`, normalized_name; optional company rollup for multiple share classes |
| `securities` | `id`, security_type (equity/etf/cash/other), display_ticker, name, issuer_id nullable, currency; stable internal ID |
| `security_identifiers` | security_id, namespace (ticker+exchange / ISIN / CUSIP / provider-specific), identifier, valid_from/to, source; constrain scoped collisions |
| `position_snapshots` | `id`, account_id, snapshot_date, import_id, valuation_source, accepted_at; one accepted effective snapshot per account/date/source policy |
| `position_snapshot_lines` | snapshot_id, security_id or unresolved_ref, quantity `NUMERIC`, reported_value nullable, reported_price nullable, currency, original_row_ref |
| `quotes` | security_id, as_of, price `NUMERIC`, currency, provider, fetched_at, market_status; keyed with provider/as-of granularity |
| `fund_snapshots` | fund_security_id, as_of, source, source_url, fetched_at, parser_version, completeness/status, raw_file_id |
| `fund_snapshot_lines` | fund_snapshot_id, constituent_security_id nullable, raw_identifier, weight_decimal `NUMERIC`, asset_type, raw_payload `JSONB`, match_status |
| `imports` | account_id nullable, file_id, type, content_hash, source, parsed_at, status, effective_date, parser_version, diagnostics |
| `files` | id, content_hash, private storage key, mime_type, size, encryption metadata, retention/status |
| `manual_overrides` | field/entity reference, value, reason, source, effective date; preserve original values |
| `jobs` | id, type, payload `JSONB`, status, run_after, attempt_count, locked_at, idempotency_key, last_error; Stage 2 |
| `financial_transactions` | account_id, provider_transaction_id nullable, posted_at, amount, currency, type, category, transfer_group_id, import_id; Stage 2 |
| `tax_lots` | account_id, security_id, acquired_at nullable, initial/remain_quantity, initial/adjusted_basis, source, verified/status; Stage 3 |
| `tax_lot_adjustments` | tax_lot_id, adjustment_type, basis_delta, quantity_delta, source; Stage 3 |
| `research_documents` | security/issuer, title, URL, published_at, retrieved_at, content hash, text/section metadata; Stage 5 |

**Important distinctions:**

- A *position snapshot* means what the user owned at an instant; it is **not** a buy/sell transaction. Do not infer purchase price or purchase history from it.
- A *fund holdings snapshot* means what the fund reported at an instant; it is **not** the user's security position. Its weights generally are not synchronized intraday with the user's quote valuation.
- A *tax lot* is associated with the owner's real, tradable security position, not with an ETF constituent in look-through output.
- `issuer_id` is optional: many instruments cannot be sensibly rolled up to an operating company.
- IDs are application-generated UUIDs; all schema, relation and index definitions must compile on PostgreSQL 16 and DSQL. Use DSQL-supported foreign keys and small bounded `JSONB`; avoid PostgreSQL extension columns, triggers and unverified server-side functions.
- Large ETF and statement imports use unpublished staging snapshots, bounded batch transactions and a final atomic revision publish so interrupted imports never leak half-loaded portfolios.
- Store quantities and weights in decimal form (`0.08` for 8%), with **explicit unit/scale** in import adapters to avoid percentages accidentally being multiplied by 100 twice.

## 5. Exposure calculation and correctness

Given a portfolio valuation timestamp `T`, base currency `C`, an account-filtered set of positions `P`, and selected dated ETF holdings snapshots:

```text
position_value(p) = quantity(p) × usable_price(p,T) × FX(price_currency,C,T)
portfolio_nav = sum(position_value(p) for included positions)
security_exposure(s) = direct_value(s)
                     + sum(ETF_position_value(f) × effective_weight(f,s))
issuer_exposure(i) = sum(security_exposure(s) for securities mapped to issuer i)
portfolio_weight(x) = exposure_value(x) / portfolio_nav
```

**MVP:** allow direct equities, cash and one ETF holdings level. Support nested ETFs later only with a bounded, cycle-safe recursive traversal and explicit residual exposure. Use `Decimal` throughout. Preserve direct holdings in `Owned positions`; the look-through is a *derived view* of the same NAV, not additive assets.

**Unclassified / residual:** for a fund with 92% recognized constituents and 5% reported cash, assign the remaining 3% of that fund position to a displayed residual bucket; if weights exceed an acceptable tolerance or leverage/shorts exist, display an unsupported/non-normalized warning instead of forcing weights to 100%. Missing holdings cause the entire fund position to remain opaque, but it is still part of portfolio NAV. Never normalize incomplete constituent percentages to 100%.

**Timestamp policy:** tag output with a portfolio position date, quote times, each ETF holdings as-of date, and report generation time. Display material currency/valuation mismatches as quality warnings.

**Performance:** precompute only after historical data becomes available, with a versioned methodology. Do not claim true historical fund look-through when historical snapshots are missing.

## 6. Backend API outline (illustrative, versioned `/api/v1`)

- `GET/POST /accounts`, `PATCH /accounts/{id}`
- `GET/POST /securities`, `GET /securities/resolve?q=`
- `GET/PUT /accounts/{id}/positions` (manual snapshot workflows)
- `POST /imports/positions/preview`, `POST /imports/{id}/commit`, `GET /imports/{id}`
- `GET /portfolio/owned?as_of=&account_ids=`
- `GET /portfolio/exposure?level=security|issuer&as_of=&account_ids=`
- `GET /portfolio/exposure/{issuer_or_security_id}/breakdown`
- `GET /funds/{security_id}/snapshots`, `POST /funds/{security_id}/refresh`, `POST /funds/{security_id}/upload`
- `GET /market-data/quotes/status`
- Later: transactions, categories, tax-lot simulation, research, async job status.

Avoid API-generated recommendations or direct execution endpoints. Use pagination for large holdings tables and version response envelopes for derived metrics and source-quality disclosures.

## 7. Background work, caching and offline operation

- During Stage 1: `refresh_quotes`, `refresh_fund_holdings`, `recompute_portfolio` CLI commands callable manually and by local scheduler. Keep externally fetched data outside an open DB transaction.
- During Stage 2: implement a provider-neutral job abstraction with idempotency keys and safe retries; use local PostgreSQL polling and a validated DSQL optimistic lease or AWS SQS for cloud, never an assumed `SKIP LOCKED` cross-target contract. Store diagnostics without leaking source documents.
- Cache source observations by provider/security/as-of/response hash; retain historical fund snapshots. Recalculate derived exposure on demand initially; memoize by portfolio snapshot + quote revision + fund snapshot IDs if queries get slow.
- **Offline contract:** a manually entered portfolio and imported/local ETF CSV can be viewed and recalculated without external networking, API keys or an AI model.

## 8. Testing strategy

- Domain unit tests for position values, currency/percent scaling, security-vs-issuer rollup, fund residuals, duplicate identifiers, unknown assets and negative/leverage cases.
- Integration tests against a real ephemeral PostgreSQL 16 instance, plus gated real Aurora DSQL integration tests for schema creation/upgrades, foreign keys, index readiness, IAM token refresh, bounded transactions, OCC retries and concurrent import/job idempotency. Never claim DSQL was tested when the cloud suite was skipped.
- Provider contract tests using pinned, **synthetic or redistribution-permitted** fixtures; do not require live issuer sites in routine CI.
- End-to-end Playwright smoke: add account → manual positions → upload fixture ETF holdings → inspect NVIDIA drill-down → export.
- Security tests for upload size, MIME mismatches, path traversal, URL allowlists, local-only binding and blocked unconsented cloud AI use.

## 9. Aurora DSQL transaction and migration guardrails

- Keep writes well below DSQL's 3,000-row, 10 MiB and five-minute transaction limits; Stage 2 ingestion uses bounded idempotent batches and a final atomic snapshot publication. Retry the full **database** unit after OCC conflicts without repeating network/model work.
- New migrations must run independently on PostgreSQL 16 and DSQL; DSQL requires DDL separate from DML, at most one DDL per transaction, and `CREATE INDEX ASYNC` readiness checks.
- DSQL currently supports UUID, `NUMERIC`, foreign keys and `JSONB` (bounded metadata). Do not depend on PostgreSQL-specific triggers, extension types, `TRUNCATE`, temporary tables, `pgvector` or assumed `tsvector` capabilities.
- Include storage, query DPU and external AWS service costs in deployment review. The **100,000 DPU / 1 GB-month** monthly allowance belongs to DSQL only; the full AWS deployment is not automatically free.

## 10. Avoid premature abstractions

- No event-sourcing framework: immutable snapshots + append-only import/audit records are sufficient.
- No trading engine or generalized portfolio optimizer in the MVP.
- No microservice for AI and no streaming quotes infrastructure. Optional **local-only** pgvector exploration is allowed behind a `ResearchIndex` interface; DSQL production must use a verified separate retrieval implementation if advanced semantic search is needed.
- No speculative support for every financial instrument. Surface unsupported types honestly and add them when user value justifies it.
