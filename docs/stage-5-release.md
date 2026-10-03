# Stage 5 implementation status

**Status:** safe offline slices of S5.1.1, S5.2.1, S5.3, provisional evidence validation, and S5.6 evaluation implemented; shared SEC/IR retrieval, AI synthesis, monitoring, live DSQL, and hosted promotion remain gated
**Updated:** 2026-10-03

This record separates finance-owned offline research workflow evidence from shared-service and provider capabilities that have not been integrated. No SEC data, personal portfolio context, or personal-AI service was requested or called during this implementation.

## Scope and dependency review

The implementation follows [the Stage 5 plan](stage-5-implementation-plan.md), [roadmap](05-roadmap.md), and [ADR 0001](adr/0001-shared-personal-ai.md). Before coding, the current `personal-ai-system` research API and contracts were inspected read-only. Its research surface is a session workflow (`POST /v1/research`, followed by a streaming `/run`) whose request contains a question, freshness mode, and idempotency key. Its owner is resolved from an authenticated user token. Finance's current `PersonalAIClient` still exposes extraction only; there is no agreed finance service identity, issuer/filing/date eligibility request, approved evidence excerpt transport, or owner propagation contract. The service's user-token session API is not treated as a finance service contract.

Finance therefore does not make a guessed HTTP call or start transmitting portfolio holdings, account/fund context, or thesis notes. Generic search, SEC/IR retrieval, evidence storage/indexing, and model synthesis remain upstream. The safe local baseline registers public SEC filing references and reported values only when a user enters them; every such item is explicitly `user_supplied_unverified`. No source contents are downloaded or represented as checked against SEC.

## S5.1 — Offline source and fact baseline

Added portable `research_documents` and `reported_facts` records with PostgreSQL Alembic revision `0016_stage5_research_sources` and an independent DSQL migration plan. The API accepts bounded SEC-hosted filing metadata and Decimal fact values. It preserves accession, CIK, filing and fiscal period, taxonomy/concept, unit/currency, raw and normalized values, source URL, registration time, and quality status. Repeated filing registration with identical metadata and repeated fact idempotency keys are stable; conflicting reuse is rejected. Reads are issuer/document scoped and bounded.

The SEC access/source check was reverified against official pages on 2026-10-03 and recorded in [the source register](03-data-sources.md#5-company-financials-and-regulatory-research--stage-5). `data.sec.gov` public JSON is documented as keyless and unavailable to browser CORS; SEC access guidance requires an identifying `User-Agent` and sets a 10 requests/second aggregate cap. This run made no SEC request. The fixture `fixtures/stage-5/synthetic-company-research.json` contains invented, non-resolving SEC-shaped identifiers and values only.

## S5.2 — Deterministic company view and research baseline

Added a bounded issuer view, manual filing/fact entry, sourced fact table, and explicit prior/current comparison. Comparison requires matching issuer, taxonomy, concept, unit, currency, period kind and fiscal period, consecutive fiscal years, and compatible date windows. Calculations use `Decimal`; missing values and non-positive denominators are explicit. Every source observation remains visible, including records that could be duplicate contexts or amendments; no observations are silently consolidated. The view shows filing dates, local registration dates, context references, original values, unverified quality, accession/form and original source link.

`research_runs` and `research_results` (revision `0017_stage5_research_runs`) freeze a deterministic, source-linked selection with a bounded result hash and idempotency key. This path contains no model-generated inferences and does not modify canonical positions, prices, transactions, or lots. Finance uses the upstream API inspection described above as a contract gate: no SEC/IR retrieval, shared evidence, private portfolio context, personal-AI request, or AI synthesis occurs. The UI remains available when all such services are disabled.

This completes only the safe manual/offline part of S5.2.1. Automated taxonomy normalization, amended-filing relationships, upstream search, and stale-cache behavior depend on source/retrieval contracts and remain unimplemented. S5.2.2 cited model synthesis remains gated on S5.3 privacy/context boundaries, S5.4 evidence contract/authorization, and explicit inference/data-handling approval.

## S5.3 — Frozen local portfolio context and user notes

The deterministic baseline may now include a verified immutable Stage 1 portfolio report. Finance checks the report artifact hash, takes only the selected issuer's report row, and verifies that direct plus ETF-derived contributions reconcile to the reported issuer total. It freezes the calculation/report input hash, valuation time, account filter IDs, per-account contribution amounts, position/quote/fund snapshot IDs, source dates and quality fields. Direct ownership and ETF look-through stay separate. A report with no issuer mapping is saved with an explicit `issuer_unmapped` status and unknown exposure, not zero exposure. The bundle does not include full portfolio NAV, canonical financial writes, or transmission to an AI/search service. Source-detail snapshots are bounded at 100 contribution rows; a larger issuer row is rejected with guidance to create a narrower report.

Added immutable, versioned user thesis notes and append-only watchlist changes. A run can select a specific note version; it is retained locally as user context and is not represented as external evidence. Later position reports or note revisions do not rewrite old research results. PostgreSQL revision `0018_stage5_portfolio_context` adds notes, watchlist events, and report/note lineage for runs; the separate DSQL plan contains one DDL statement per step and asynchronous indexes.

The current upstream personal-AI contract still does not establish authorization or a reviewed privacy-minimized service payload, so the private context bundle remains local. Earnings/report histories can only contain references a user manually entered; no automatic document/report refresh or model interpretation is implemented.

## S5.4 — Provisional local evidence boundary

Added `app/integrations/research_evidence.py` with a finance-side issuer/document scope, as-of/freshness policy, source identity fields, excerpt byte/count limits, and evidence candidate validation. The validator rejects missing or mismatched issuer/document/accession/URL/date identity, stale or future retrieval times, missing content hashes/excerpts, untraceable byte offsets, and oversized results. Different content hashes for the same registered filing remain together as an explicit conflict group. Empty/too-thin evidence reports `insufficient`; no result is silently truncated. Unit fixtures use only the existing invented, non-resolving SEC-shaped data.

This schema is a **provisional finance validation envelope**, not an agreed personal-AI request/response contract. It does not provide HTTP transport, retrieval, caching, indexing, source parsing, or model routing. Its identity/hash/offset checks validate the service's metadata claims against the user's registered reference; they do not fetch SEC content or independently verify excerpts. The existing immutable finance research result and DSQL migration plan remain independent of generic upstream index storage. No evidence candidate from a service is currently persisted or rendered.

## S5.5 — Public monitoring deferred at the job gate

No scheduled monitor, public-source poller, notification sender, or monitoring schema was added. S5.3 watchlist entries remain user-edited local state and do not imply refreshes or alerts. The Stage 2 release record says the existing PDF worker is partial: worker restart/cancellation acceptance, output reuse, cleanup, benchmark, and live DSQL lease evidence remain outstanding. Its worker is a local in-process PDF-preview path, not an approved research scheduler or a production SQS/DSQL worker. Stage 2 itself is explicitly not complete.

This blocks a safe S5.5 implementation because monitoring requires durable idempotent scheduling/retry/cancel semantics, deduplication across amended source content, restart recovery and cleanup, and delivery receipts independent from source/model work. The DSQL compatibility contract requires live concurrent-claim, lease-expiry, stale-completion, cancellation, and retry evidence before relying on a database lease. A source refresh/notification path also needs an approved source scope, cadence, retention, user notification preference/channel, and verified source rights. None of these gates were established here. No provider, personal data, DSQL cluster, or notification channel was contacted.

### Remaining gates

- **S5.1.2 shared public observations:** not implemented. Requires an agreed service request/response contract with issuer and filing eligibility, retrievable provenance/excerpts, size/freshness limits, and service authorization. Upstream's current session/SSE API does not establish that contract.
- **S5.2.2 synthesized cited research:** not implemented. The only enabled path is the deterministic, user-entered source/fact baseline. No model output is emitted or treated as evidence.
- **S5.3 remote context/inference and automatic report history:** not implemented. Portfolio context and thesis notes remain local; only manually registered filings are available.
- **S5.4 shared evidence retrieval:** not integrated. The upstream contract, authorization, evidence provenance, and owner propagation remain unresolved; no finance index/search/database is added.
- **S5.5 monitoring:** not implemented. Stage 2 job delivery, restart, cleanup, and live DSQL lease acceptance remain partial/unverified; source cadence/rights and notification policy are undecided.
- **S5.6 evaluation/release:** an offline synthetic evaluation slice is implemented and reported in [the Stage 5 evaluation report](stage-5-evaluation.md). It verifies deterministic fixture arithmetic, registered citation identity, a local-only evidence-scope shape, disabled research behavior, and unchanged canonical account/position/transaction rows. Semantic claim support, quote traceability, public source accessibility, upstream parity, browser E2E, PostgreSQL runtime, and real DSQL remain unverified; this is not a Stage 5 or hosted release pass.

## S5.1 verification

- `UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage5_research.py tests/test_dsql_migrations.py` — **14 passed**. Coverage includes synthetic registration/listing, duplicate/conflict handling, URL/period/precision validation, DSQL plan structure, single-statement DDL and async indexes.
- Changed Stage 5 Python files passed Ruff lint and formatting checks.
- `pnpm api:generate` exported OpenAPI and regenerated `apps/web/src/api/schema.d.ts`; `pnpm api:check` passed. The bundled Node runtime and `/private/tmp` uv cache were needed in this shell.
- Local PostgreSQL was unavailable on port 55432, so Alembic migration runtime was not exercised on PostgreSQL. The migration is structurally represented in DSQL tests only; live Aurora DSQL remains unverified.
- No SEC, personal-AI, real-data, browser-hosted, or cloud call was made.

## S5.2 verification

- `UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage5_research.py tests/test_dsql_migrations.py` — **16 passed**. Synthetic coverage includes fiscal-period/unit incompatibility, missing/zero baseline behavior, source linkage, idempotency, frozen result integrity, and DSQL migration structure.
- Changed research modules passed mypy and Ruff. The frontend passed `pnpm --dir apps/web typecheck`, `pnpm api:check`, and `pnpm --dir apps/web build`; the build reports the existing large-chunk advisory.
- Migration 0017 is represented in the DSQL migration plan, but PostgreSQL runtime and real Aurora DSQL remain unverified because no local database/cluster is available.

## S5.3 verification

- The focused synthetic research and DSQL migration checks passed **17 tests**. They verify the $35,200 issuer context fixture ($30,000 direct + $5,200 ETF-derived), per-account/source rows, note and watchlist revisions, explicit unmapped issuer handling, and frozen historical results after later position/note changes.
- Changed research Python files passed mypy/Ruff; the generated OpenAPI TypeScript client passed typecheck, formatting, and lint. The web production build succeeds with the previously noted large-chunk advisory.
- Migration 0018's local PostgreSQL execution remains unverified because no disposable PostgreSQL service was available. DSQL structure/resume checks passed, but live DSQL schema, FK, JSONB and OCC behavior remain unverified.

## S5.4 verification

- `UV_CACHE_DIR=/private/tmp/codex-finance-stage5-uv-cache uv run --directory services/api --locked pytest -q tests/test_stage5_evidence.py` — **4 passed**. Fixtures cover scoped identity, missing attribution, stale dates, offset mismatch, source conflicts, insufficient evidence, and item/byte limits.
- The validator module and synthetic test passed mypy and Ruff. No personal-AI/SEC/IR transport was called; upstream wire compatibility and evidence authenticity remain unverified by design.

## S5.5 verification

- Reviewed [`docs/stage-2-release.md`](stage-2-release.md) and [`docs/07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md): Stage 2 S2.6 is partial; restart/cancellation acceptance, parsed-output reuse, cleanup, and real DSQL lease tests remain required. The Stage 2 local worker is in-process and handles PDF preview only.
- No S5.5 code or tests were added because the durable scheduling and delivery gates are not met. Existing watchlists are manual and offline; they do not fetch or notify.

## S5.6 offline evaluation

- See [the dated synthetic evaluation report](stage-5-evaluation.md). Its harness checks the fixture's exact `$20,000,000` / `20%` comparison, binds each citation to the selected fact and manually registered accession/URL, preserves a hostile user-authored thesis as a note with no generated inference, checks the local evidence-eligibility shape for absence of portfolio/account/note content, and confirms the baseline succeeds with the default disabled AI client without changing canonical financial row counts.
- The citation check validates record identity, not source accessibility, excerpt authenticity, quotation fidelity, or semantic claim support. No generated claim exists to evaluate. S5.4 validator tests cover stale, wrong-scope, conflict, insufficient, untraceable, and oversized synthetic candidates.
- No shared provider, public filing, or personal data was used. No upstream comparison, provider failure/idempotency, browser journey, live PostgreSQL persistence, or real DSQL test ran. The offline evaluation does not clear the unresolved S5.2.2 or hosted release gates.
- The full API suite passed **195 tests**, with **37 PostgreSQL/DSQL opt-in tests skipped**; the web suite passed **9 tests**. Full Python mypy/Ruff and the generated API check passed. Web typecheck and production build passed (existing 536 kB chunk advisory). The report records two remaining repository checks: web ESLint has four existing state-in-effect findings, and whole-tree Ruff format check reports existing differences in applied migrations `0007` and `0015`; changed Python files are formatted. The migration-count and current-head regression expectations were updated for the Stage 5 schema.
