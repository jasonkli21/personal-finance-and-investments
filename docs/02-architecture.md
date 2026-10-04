# Technical architecture and data model

Updated 2026-10-03. Local finance/planning and offline research are implemented; cloud and live-service gates remain. [ADR 0002](adr/0002-gcp-neon.md) defines the production target.

## 1. Architecture decision

A React/Vite SPA calls one modular FastAPI backend. SQLAlchemy/psycopg uses PostgreSQL 16 locally and ordinary Neon PostgreSQL in cloud. Alembic is the only schema history. Local and hosted databases are independent. Domain logic does not branch on provider.

```text
Local: Vite -> /api proxy -> FastAPI -> PostgreSQL 16 / PrivateFileStore
Cloud: Firebase Hosting -> /api/** -> Cloud Run API
                                      |-- Neon PostgreSQL (runtime pool)
                                      |-- GCS private originals/artifacts
                                      |-- Secret Manager / service identity ADC
                                      +-- invoke bounded Cloud Run Job
                                           -> same Finance DB job/lease fences
Artifact Registry -> immutable API / worker image
Alembic -> optional direct Neon migration connection
PersonalAIClient -> disabled; independently reviewed transport required
```

Finance owns authoritative data, deterministic Decimal math, source validation, staged review/publication, workflow and UI. Shared generic extraction/retrieval/models/memory belong in personal-ai-system behind a separately gated service contract. No shared database/store or upstream module imports. Startup installs a disabled PersonalAIClient and rejects activation. Manual research and provisional evidence validation do not establish live retrieval or synthesis.

## 2. Technology and deployment boundaries

React/TypeScript/Vite, Tailwind, TanStack Query/Table, generated OpenAPI types; shadcn/ui and ECharts remain optional. Python/FastAPI/Pydantic, SQLAlchemy 2, psycopg 3, Alembic, uv/pnpm, Docker Compose. Provider interfaces retain manual fixtures and offline operation. No new microservice, queue or vector database.

DATABASE_URL accepts normal PostgreSQL URLs; optional MIGRATION_DATABASE_URL serves Alembic/direct operator connections. Production validates Neon host and verify-full/system-root TLS. Bounded pools, pre-ping, connect/recycle settings and DB-only serialization/deadlock retries apply to both environments. No independent dialect, token generator or migration ledger. Applied revisions are immutable. See [database contract](07-postgres-neon.md).

FileStore remains a put/read protocol. PrivateFileStore keeps owner-only local files; GCSFileStore uses service ADC, create-only generation preconditions, generation-pinned bounded reads and hash/length verification. All preview/download access is through authenticated backend routes, never public object URLs.

Provider-neutral OIDC/PKCE and server-side revocable sessions remain the auth architecture. Firebase preserves /api and strips ordinary cookies; explicit ASGI path handling and a signed __session envelope transport the existing OIDC transaction and DB session token. Exact origin/CSRF and issuer/audience/subject/scope checks protect both Firebase and direct Cloud Run access. SameSite=Lax is needed for cloud OIDC redirect transport; session expiry/revocation and write-origin checks remain enforced.

## 3. Current layout

- apps/web/src: workspaces, shared auth/revision/upload helpers and generated API schema; test and e2e live alongside it.
- services/api/app/api: HTTP contracts/routes; domains: current flat finance modules (accounts, securities, portfolio, imports, funds, exposure, reports, documents, transactions, finance_summary, jobs, history, performance, tax, sales, portfolio_scenarios, planning, research).
- app/db: one engine/URL/session boundary, ORM metadata and bounded retry. services/api/alembic: canonical applied revisions.
- app/auth: OIDC, owner binding, sessions and Firebase transport. app/storage: local and GCS behind FileStore.
- app/jobs: local polling, bounded worker command and Cloud Run invocation adapter. app/ingestion: bounded text-PDF child process.
- app/integrations: disabled PersonalAI extraction and provisional research-evidence boundary.
- app/recovery: encrypted portable archive/isolated restore; app/release: Neon evidence and fail-closed Stage 4 gate.
- infra/terraform: prepared GCP infrastructure and Firebase configuration output; tests/infra: offline guardrails. fixtures: synthetic only.

Existing shared quote selection, revision-bound drafts, atomic reviewed publication and flat domain ownership remain useful. Broader Stage 2 lifecycle, OCR/sync and live research work stays partial/gated.

## 4. Conceptual relational schema

The following is a **logical design**; create exact migrations incrementally. Include `created_at`, `updated_at` and owner/scope where relevant. Favor immutable dated snapshots over in-place mutation of external observations.

| Table / concept | Representative fields and invariants |
| --- | --- |
| `accounts` | `id`, name, account_type, base_currency, active, source_type, current manual-position revision and selected snapshot pointer; account identity is independent of brokerage |
| `issuers` | `id`, normalized_name; optional company rollup for multiple share classes |
| `issuer_aliases` | issuer_id, alias namespace, alias, normalized_alias, source, review status; cross-issuer collisions remain ambiguous until reviewed |
| `securities` | `id`, security_type (equity/etf/cash/other), display_ticker, name, issuer_id nullable, currency; stable internal ID |
| `security_identifiers` | id, security_id, namespace, exchange, value/normalized_value, valid_from/to, source, review status; uniqueness is scoped by namespace, exchange, normalized value and interval start |
| `position_snapshots` | `id`, account_id, snapshot_date, source, immutable revision, import_id, valuation_source, accepted_at; replacements append a revision and an account pointer selects one accepted revision |
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
| Future research references/results | security/issuer, upstream evidence/run IDs, source URL/dates/hash, validation status and saved finance workflow; Stage 5. Generic evidence/index/memory storage is upstream, not shared SQL. |

**Important distinctions:**

- A *position snapshot* means what the user owned at an instant; it is **not** a buy/sell transaction. Do not infer purchase price or purchase history from it.
- A *fund holdings snapshot* means what the fund reported at an instant; it is **not** the user's security position. Its weights generally are not synchronized intraday with the user's quote valuation.
- A *tax lot* is associated with the owner's real, tradable security position, not with an ETF constituent in look-through output.
- `issuer_id` is optional: many instruments cannot be sensibly rolled up to an operating company.
- IDs are application-generated UUIDs; all schema, relation and index definitions use ordinary PostgreSQL. Alembic is canonical locally and in Neon; retain bounded JSONB and tested relational invariants.
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

**Stage 1 execution policy:** the reviewed [Stage 1 plan](stage-1-implementation-plan.md#deterministic-selection-and-financial-policy) specifies default account-pointer versus explicit historical selection, quote precedence and line-scoped price fallback, immutable same-date corrections, USD-only incomplete totals, signed/opaque treatment and exact reconciliation. Account filters select NAV; row search/top-N retain that denominator. Freeze input policies and issuer mappings with selected observation IDs in a durable immutable calculation record/private derived artifact; paginated output, drill-down and export use the same calculation UUID across edits and process restarts. Reports do not add authoritative positions. Catalog creation and review corrections must work without a demo seed.

**Performance:** precompute only after historical data becomes available, with a versioned methodology. Do not claim true historical fund look-through when historical snapshots are missing.

## 6. Backend API outline (illustrative, versioned `/api/v1`)

The actual backend currently uses `/v1`; Vite strips `/api` locally; Firebase preserves it and the backend ASGI prefix adapter strips it before route/auth handling. Stage 1 preserves this routing and generates exact paths from OpenAPI. The prefixes below describe the browser-facing conceptual API, not an instruction to rename existing backend routes.

- `GET/POST /accounts`, `PATCH /accounts/{id}`
- `GET/POST /securities`, `GET /securities/resolve?q=`
- `GET/PUT /accounts/{id}/positions` (manual snapshot workflows)
- `POST /imports/positions/preview`, `POST /imports/{id}/commit`, `GET /imports/{id}`
- Review correction/acknowledgement and cancellation actions with expected review revision; concrete Stage 1 routes are defined in OpenAPI.
- `GET /portfolio/owned?as_of=&account_ids=`
- `GET /portfolio/exposure?level=security|issuer&as_of=&account_ids=`
- `GET /portfolio/exposure/{issuer_or_security_id}/breakdown`
- `GET /funds/{security_id}/snapshots`, `POST /funds/{security_id}/refresh`, `POST /funds/{security_id}/upload`
- `GET /market-data/quotes/status`
- Delivered later-stage routes include transactions/categories/transfers, finance balances/summaries, investment history/performance, tax-lot review/adjustments, hypothetical simulations/planning, local research, and job status/cancellation. OpenAPI defines their exact contracts.

The Stage 0 implementation exposes account create/list/patch, bounded local security resolution, and account-scoped manual position GET/PUT. Manual replacement compares a per-account revision counter, appends a new snapshot and lines, and moves the account's selected-snapshot pointer in one transaction. Prior revision payloads and lines remain immutable; lifecycle status can change from accepted to superseded. Replacing the current selection does not erase prior contents and may select any effective date. Financial values cross OpenAPI as strings; manual price date is the snapshot effective date. Avoid API-generated recommendations or direct execution endpoints. Use pagination for large holdings tables and version response envelopes for derived metrics and source-quality disclosures.

## 7. Jobs and offline operation

Local polling uses durable conditional lease owner/generation/expiry/cancellation fences inside each staging/completion unit. Cloud API commits enqueue before triggering a bounded Cloud Run Job over the same worker logic. Repeated triggers cannot duplicate publication; the DB row is authority. Retry/backoff and abandoned-lease recovery run within the execution bounds. Failed invocation or remaining backlog requires identical-upload retry or explicit operator drain; hosted lifecycle/restart acceptance remains pending. No new queue/scheduler is assumed.

Local/manual quote observations, reviewed issuer-download uploads and frozen reports remain available offline. Live issuer refresh reports unavailable. No model, bank or market call occurs as a migration side effect. Cache/research expansion requires separately requested product work.

## 8. Validation and promotion

Run pnpm check for generated contracts, lint/format/types, backend/web/infra tests and build. Disposable PostgreSQL tests verify fresh/populated migration, finance workflows, concurrency/jobs and encrypted recovery; browser journeys require their disposable loopback gate. Real Neon migration/reconnect/concurrency and GCP HTTPS/auth/private-object/recovery checks remain required for promotion. Schema, fixture, build, image, infrastructure and configuration fingerprints bind evidence; missing/skipped/stale checks fail closed. See [migration validation](gcp-neon-migration.md) and [Stage 4 operations](stage-4-operations-runbook.md).
