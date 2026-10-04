# Stage 2 implementation plan

**Status:** In progress; S2.1 local text-PDF preview slice, S2.3 local transaction workflow, S2.4 summary/balance views, and S2.6 PDF job workflow are partial; S2.2 gated; S2.5 evaluated and deferred
**Updated:** 2026-10-02
**Roadmap coverage:** Work packages 2.1–2.6

This is the execution plan for reviewed document-assisted holdings and personal finance. It extends [Stage 1](stage-1-implementation-plan.md) without changing snapshot semantics or making AI/account connections mandatory. Read [ingestion and AI](04-ingestion-and-ai.md), [the product specification](01-product-spec.md), [source policy](03-data-sources.md), [security](06-security-and-deployment.md), and [PostgreSQL/Neon contract](07-postgres-neon.md) first.

## Scope boundary

Stage 2 extends Stage 1 private document storage with deterministic institution-specific text-PDF/CSV parsing, optional shared generic OCR/structured candidate extraction through `PersonalAIClient`, reviewed transaction imports, merchant/category rules, splits/refunds/transfer matching, spending/net-worth views, and same-codebase asynchronous processing. Read-only account sync is optional and independently gated.

The smallest vertical slice is **upload synthetic brokerage text PDF and bank/card CSV → inspect row evidence and discrepancies → accept revision → view reconciled holdings/spending**. Modules are `ingestion`, `spending`, `portfolio`, `securities`, storage, the personal-AI service boundary, account-provider adapters, and `jobs`.

Tax-lot accounting/performance/sale planning, trading, general agents, mandatory remote inference, password scraping, automatic trusted imports, and new cloud application infrastructure are excluded. Preserve provided lot fields as source evidence for Stage 3; do not infer them.

Per [ADR 0001](adr/0001-shared-personal-ai.md), models, generic extraction/OCR runtime, research, AI memory and evaluation infrastructure belong in personal-AI. Finance owns institution-specific mappings, domain schemas, source evidence, validation, review and publication. Stage 1 supplies only a disabled extraction seam; add one real capability after agreeing upstream transport/versions and reviewing consent, retention and authorization. Do not introduce a second `StructuredModelProvider` or local model stack here.

## Delivery conventions and cross-cutting requirements

- Reuse Stage 1 file identities, review revisions, bounded batches, and atomic publication; generalize only where the new document types need it.
- Separate immutable file, parse attempt, extracted document, user correction, staging revision, and published financial record. Reprocessing is not a second financial event.
- No parser/model/network operation runs inside a write transaction or database retry. Store reusable extraction results privately before staging.
- Local parsing is first. Model-disabled operation, missing OCR/model binaries, and manual correction are supported outcomes.
- Remote inference is disabled by default and cannot become a silent fallback. Real statements require explicit provider/data-handling review and opt-in; Gemini unpaid services are prohibited for sensitive statements under the existing policy.
- Every amount/identifier/date has raw value, evidence reference, normalized value, and quality/review status. Missing information stays null; arithmetic is independently deterministic.
- Imported snapshots replace owned positions. Transactions are append/update observations with explicit identity; statement differences never imply trades.
- Finance totals use Decimal, dated currencies, and published revisions. Transfers and credit-card payments are not income plus spending merely because two statements include them.
- At-least-once jobs require idempotent outputs and cancellation-safe publication. Local polling and cloud claiming share a `JobStore` interface, not a presumed PostgreSQL locking recipe.

## Required verification matrix

| Area | Required cases | Evidence |
| --- | --- | --- |
| File security | Oversize/MIME mismatch, traversal, parser timeout, preview access, malicious URL | Unit/routes/storage tests; private-file inspection |
| Extraction | Multicolumn text PDF, CSV, scan, screenshot, negative/fractional values, missing rows/dates | Synthetic checked JSON and evidence maps |
| Review/publication | Corrected field, obsolete approval, cancel, interrupted/resumed batch, duplicate statement | PostgreSQL integration and UI |
| Transactions | Native-ID updates, fingerprint collision, identical recurring purchases, refunds/splits | Domain/repository tests |
| Transfers | Two owned accounts, card payment, partial match, fees, ambiguous match | Reconciliation fixtures; no double spending |
| Models | Disabled, unavailable, invalid JSON, invented values, unconsented cloud attempt | Fakes, schema/evidence validation, privacy tests |
| Jobs | Durable DB claims, cancellation, expiry and fenced publication | Local lifecycle tests plus real bounded Cloud Run execution before hosting |
| Optional sync | No connection, expired token, permission/quota, disconnect, repeated pages | Fake/sandbox opt-in; no production dependency |
| Release | Brokerage + bank/card review journey, no AI, clean local setup | Browser smoke, OCR benchmark report, real Neon gate separately |

## Required implementation artifacts

**Required persistent records:**

| Record | Required fields / invariants |
| --- | --- |
| File | UUID/hash/private storage key, MIME/size, retention/access status, timestamps; original immutable |
| Import / parse attempt | File/account/type/source/effective period, parser/schema version, state, diagnostics, parent attempt, idempotency identity |
| Extracted row / evidence | Raw values, document page/table/row or image box where supported, normalized candidates, unresolved fields, parser/method, measurable quality flags |
| Review correction | Attempt/field/row, prior value, accepted value, reason, review revision, recorded time; previous evidence retained |
| Published transaction | Account, native provider ID if present, posted/transaction dates, signed Decimal amount/currency, raw description/type, canonical type/category, source/import revision, review status |
| Category / rule / split | Stable ID, rule priority/version/criteria, override status; split amounts sum exactly to parent amount |
| Transfer relationship | Linked transaction IDs, match method/status/reason, fee treatment, confirmed revision; ambiguous candidates remain unlinked |
| Job / attempt | UUID/type, bounded payload reference, idempotency key, status/run-after, lease owner/expiry/fencing revision, attempts, safe error, timestamps |

**Document contracts:** separate Pydantic position, transaction, and fund-composition documents. Required totals are nullable and marked reported versus calculated. Positions retain quantities/prices/values/cash/unparsed rows; transactions retain signed amounts/raw types/dates/native IDs and optional balances. Model output must reference actual input evidence, never invented page/row IDs.

**Required routes under `/api/v1`:**

| Route family | Behavior |
| --- | --- |
| `/imports` and `/imports/{id}` | Receive private document, inspect state/extracted rows/evidence, revise mapping/corrections, reprocess, cancel, commit accepted revision |
| `/files/{id}/preview` | Scoped private preview/download with validated disposition/type; never static assets |
| `/transactions` | Bounded account/date/category reads, explicit manual record/edit, audited categorization and splits |
| `/transfers` | Candidate inspection and explicit confirm/reject/unlink with reconciliation |
| `/finance/summary` | Income/spending/cash-flow/category/net-worth views with dates, currencies, exclusions, sources |
| `/jobs/{id}` | Safe progress/status/retry eligibility; no raw parser/model payload |
| Optional `/connections` | Read-only consent/link status, refresh request and disconnect; tokens never returned |

Exact suffixes/methods must be finalized in OpenAPI and the generated client before UI integration. Commands for parsers/workers/benchmarks are implementation deliverables, not existing scripts.

**Configuration:** upload/type/size bounds, private file backend/directory, parser time/memory limits, enabled parsers, `PERSONAL_AI_ENABLED=false` (currently true is rejected), future account-sync/paid-use gates, personal-AI request/response bounds and reviewed service policy, batch bounds, worker concurrency/lease/retry/cancellation policies, transaction dedup and transfer tolerances. Record actual settings/defaults in the handoff.

## Dependency map

```text
Stage 1 ─> S2.1.1 File/contracts ─┬─> S2.1.2 Text extraction/review ─> S2.2 Complex documents
                                └─> S2.6.1 Job contracts/runner ─> S2.6.2 Worker integration
S2.1.2 ─> S2.3.1 Transaction identity ─> S2.3.2 Categories/transfers ─> S2.4 Dashboards
S2.3.1 + S2.6.2 ─> S2.5 Optional account sync
S2.2 + S2.4 + S2.6.2 ─> S2.6.3 Evaluation/release
```

S2.5 is optional; no exit gate for the local document workflow depends on production provider eligibility.

---

## Stage 2 — Automated statement ingestion and personal finance

### S2.1.1 — Define private files, extraction contracts, and fixtures

**Dependencies:** Stage 1 completion.  
**Modules:** storage, ingestion schemas, security tests.

**Goal:** establish a trustworthy document boundary before extraction.

**Work:**

1. Define a `FileStore` protocol for private store/read/delete metadata and implement owner-only local storage with generated keys, immutable originals, hashing, and safe cleanup.
2. Validate upload bytes/MIME/size, reject traversal and unsupported input, and bound parser invocation resources; document private preview access for local versus cloud modes.
3. Extend import states and separate document schemas, evidence locations, correction revisions, reported/calculated totals, safe diagnostic codes, and cancellation semantics.
4. Build synthetic PDFs/CSVs/images and manually checked expected structured JSON, including inconsistent totals, missing dates, unknown securities, negative values, and unparsed rows.

**Requirements:** originals are excluded from Git/public assets/logs; parser artifacts are private too. Missing fields cannot be repaired by invented dates/identifiers. Synthetic fixtures have no real account masks copied from the user.

**Acceptance criteria:** storage tests cover duplicate bytes, safe key generation, invalid MIME/path, upload/parse bounds, and cleanup without canonical changes; schema tests reject evidence references outside the document; disabled optional tools do not prevent file review/manual import.

**Out of scope:** cloud object provisioning, OCR/model integration, and publicly accessible previews.

### S2.1.2 — Implement deterministic extraction and review-to-publish

**Dependencies:** S2.1.1.  
**Modules:** ingestion parsers/review service, portfolio, web import wizard.

**Goal:** turn readable statements into reviewable, reconciled data.

**Work:**

1. Implement one text brokerage-PDF adapter and CSV document adapters using local extraction; verify selected libraries/licenses before implementation.
2. Retain page/table/row evidence, account/date candidates, raw numeric strings, unparsed rows, parser version, and partial-extraction diagnostics.
3. Validate signs, percent/currency units, `quantity × price` versus reported value, account totals, and beginning/ending balances where sufficient evidence exists.
4. Build evidence-aware corrections and before/after diff; changing parser/mapping/correction increments review revision and invalidates prior acceptance.
5. Stage only the accepted revision in bounded idempotent batches and publish atomically; recover interrupted staging and reimport without duplicate financial output.

**Requirements:** preserve discrepancies; correction records point back to original evidence. Review completion checks every unresolved row under an explicit policy. Source identity is account/statement/date/hash scoped; reprocessing the same source cannot multiply holdings.

**Acceptance criteria:** synthetic text statement replaces holdings after review; duplicate/corrected/reprocessed files retain attempt history; arithmetic mismatch/missing account or date prevents silent commit; cancelled/failed batch keeps prior holdings visible; stale approval and concurrent commit are rejected safely.

**Out of scope:** automatic trusted imports, OCR, invented trades/cost basis, and one large transaction per statement.

**Implementation status (2026-10-02):** The local slice accepts synthetic text-layer brokerage PDFs, retains originals privately, records page/line evidence and reconciliation warnings, and stages normalized rows through reviewed position import. The browser polls a durable background job and supports cancelling before publication. Scanned PDFs, institution-specific broad coverage, correction audit of document diagnostics, durable parse-stage output reuse, and end-to-end verification remain outstanding; this does not complete S2.1 or its exit criteria.

### S2.2 — Integrate shared candidate extraction with deterministic/manual fallback

**Dependencies:** S2.1.1, S2.1.2; agreed upstream extraction contract and data-handling policy.
**Modules:** `PersonalAIClient` adapter, finance candidate/evidence validation, review UI.

**Goal:** support synthetic scans/screenshots while preserving finance authority, review and privacy.

**Work:**

1. Verify upstream generic OCR/structured extraction availability, licenses, local resource bounds, provider data-use/retention and actual versioned transport. The handoff's illustrative extraction endpoint/schema is not a delivered API.
2. Extend finance-owned capability DTOs with raw fields, actual document evidence references, dates, unknown/unparsed rows and quality. Keep canonical schemas separate.
3. Add one bounded HTTP adapter behind the existing protocol: timeout/response-size/redirect limits, source/schema compatibility checks, safe disabled/unavailable/timeout/unauthorized/rate-limit/provider/invalid-response errors and deterministic HTTP contract tests. Models/providers/prompt runtime remain upstream.
4. Validate inferred identifiers, signs, quantities and totals in finance; invented/contradictory/unresolved fields remain review candidates. Persist reusable results privately before DB staging or OCC retries.
5. Preserve deterministic templates and manual correction when personal-AI/OCR is disabled/unavailable. No silent provider or paid fallback. Generic extraction may run upstream with models disabled when supported.
6. Gate all data transmission on explicit scoped consent and reviewed content/storage/egress policy; deployed private data also requires authenticated user/service identity, verified owner propagation and upstream authorization. No fixed `local` owner bypass.

**Requirements:** confidence is measurable field quality, not model probability. Redacted diagnostics omit statements/images/prompts. Finance owns original private files, validation/deduplication and reviewed atomic publication. No finance-owned Docling/model service, provider SDK or agent framework.

**Acceptance criteria:** fake/HTTP-stub candidates preserve evidence and require correction for confused numbers/identifiers; malformed output never reaches publication; disabled/outage paths permit manual import; tests block unconsented, unauthorized and wrong-owner calls before transmission. Record finance field/evidence/reconciliation/review benchmarks separately from upstream generic-model evaluations. Live/auth checks are marked unverified until run.

**Out of scope:** implementing the upstream extraction runtime, remote private-data activation without authorization, research/memory/tools, and making AI essential.

**Implementation status (2026-10-02):** Deferred at its stated dependency gate. The adjacent `personal-ai-system` currently has no agreed extraction transport, verified authenticated owner propagation, or reviewed real-data authorization/handling policy. Finance remains `PERSONAL_AI_ENABLED=false`; no statement bytes are transmitted. Revisit after those prerequisites are established.

### S2.3.1 — Implement transaction identity and canonical publication

**Dependencies:** S2.1.2.  
**Modules:** spending transactions, ingestion normalization, migrations.

**Goal:** import bank/card events without losing legitimate repeated purchases.

**Work:**

1. Define signed amount/type/date semantics and schema migrations for immutable imported observations and selected canonical transaction revisions.
2. Prefer scoped native provider IDs; define fallback fingerprints using account, statement/source evidence, dates, descriptions, amounts, and collision diagnostics.
3. Handle pending-to-posted/provider corrections without making a second expense; retain raw prior observations and review when matching is uncertain.
4. Publish an accepted transaction import through a small revision marker so readers do not see half a statement; identity conflicts fail/review rather than overwrite unrelated events.
5. Expose bounded transaction list/detail and audited manual transaction correction/entry contracts through OpenAPI.

**Requirements:** date/amount alone is never a duplicate key; exact recurring purchases may be distinct. Preserve provider IDs/raw descriptions and original signs. Snapshot imports remain separate and cannot create financial transactions automatically.

**Acceptance criteria:** importing the same card statement twice leaves counts/totals unchanged; two legitimate same-day/same-amount purchases both survive; overlapping statements, changed native-ID observation, missing ID, fingerprint collision, retry, and failed batch have documented deterministic outcomes.

**Out of scope:** investment performance/tax-lot reconstruction, automatic certainty for fuzzy duplicates, and discarding ambiguous rows.

### S2.3.2 — Add categories, splits, refunds, and transfer matching

**Dependencies:** S2.3.1.  
**Modules:** spending rules/reconciliation; transaction review UI.

**Goal:** classify cash flows without double-counting spending.

**Work:**

1. Implement versioned deterministic merchant/category rules with priority, match explanations, and user overrides that survive later rule runs.
2. Add split records whose signed amounts equal the parent exactly; categories do not create extra transactions.
3. Define refunds/chargebacks, unknown categories, and credit/debit statement conventions without guessing sign inversions.
4. Propose transfer pairs using accounts, dates, signed amounts/currencies, and tolerances; require confirmation for ambiguity and retain unmatched sides visibly.
5. Distinguish credit-card payments, brokerage deposits, owned-account transfers, and fees; expose link/unlink with audit/reconciliation.

**Requirements:** confirmation changes classification/relationships, not raw evidence; transfer fees remain expenses; missing counterpart never fabricates a balancing event. Category changes and splits use optimistic revisions.

**Acceptance criteria:** a card purchase plus payment counts spending once; an owned-account transfer is not both income and expense; split totals reconcile; refunds reduce spending under the documented convention; ambiguous/partial/cross-currency transfer candidates stay reviewable; manual overrides are not lost after reruns.

**Out of scope:** AI-required categorization, tax deductibility, and automatic inferred transactions.

### S2.4 — Deliver reconciled finance and net-worth views

**Dependencies:** S2.3.1, S2.3.2; Stage 1 owned valuation.  
**Modules:** spending summary services, portfolio/net worth, web dashboards.

**Goal:** explain monthly spending and owned wealth from accepted data.

**Work:** implement monthly income/spending/category/cash-flow queries with posted-date policy; add manual off-card expenses and source-labelled balance observations; compose unified net worth from actual included asset/liability balances with explicit credit-card sign conventions; display statement/calculated reconciliation, exclusions, gaps, currencies, and dates; build accessible tables/charts with drill-through to transactions.

**Requirements:** balances, transactions, and ETF decomposition have different purposes; do not add look-through to wealth or sum duplicate balance representations. No performance/return claim from snapshots. Missing account coverage and unconverted currencies remain visible.

**Acceptance criteria:** category subtotals equal canonical categorized/uncategorized spending under the documented transfer/refund policy; cash flow matches accepted transactions; card liability and payment treatment do not inflate net worth; account/date filters reproduce drill-down; stale/missing balances are labelled; zero/empty months render meaningfully.

**Out of scope:** forward planning, tax estimates, guaranteed complete finances, and investment returns.

### S2.5 — Evaluate optional read-only account synchronization

**Dependencies:** S2.3.1, S2.6.2; provider/privacy/cost review.  
**Modules:** account adapter, encrypted server token storage, optional connection UI.  
**Decision required:** institution/product eligibility and explicit read-only connection consent.

**Goal:** automate observations when viable while preserving manual/document workflows.

**Work:** verify current official Plaid eligibility, product coverage, costs, native-ID/update semantics, nullable basis/lot fields, and retention; begin with fake/sandbox consent and pagination; use hosted link flow, encrypted server-side tokens, intentional Investments/Transactions scopes, cached observation/import review, disconnect and revocation handling; document any permitted scheduling/refresh limits.

**Requirements:** account consent does not imply remote-AI consent or trusted auto-commit. Keep sync observations reviewed by default unless a specific trusted path is separately approved. Empty lots mean unavailable, not zero basis. No banking passwords/trade permissions stored.

**Acceptance criteria:** fake/sandbox pagination and retry are idempotent; expired/revoked/quota/malformed responses produce safe status; disconnect stops refresh and applies documented retention; manual/PDF imports work with sync disabled; production eligibility/unexecuted checks are reported honestly. If no acceptable free route exists, finish the evaluation and defer the connector.

**Out of scope:** required production subscription, paid fallback, credential scraping, and reliable lots inferred from aggregate basis.

**Implementation status (2026-10-02):** Sandbox-only evaluation; production connection work remains optional and gated. Plaid's official documentation describes account holdings/transactions products, but pricing is subscription-based and exact eligibility/fees depend on an approved account. No credentials, hosted Link flow, token storage, refresh adapter, or production sync has been added. Manual imports remain the supported path.

### S2.6.1 — Define durable job claiming and retry contracts

**Dependencies:** S2.1.1.  
**Modules:** jobs repository/runner, database migration.

**Goal:** process documents asynchronously with explicit ownership and recovery.

Finance job rows are authoritative: persist idempotent enqueue, attempts, lease owner/expiry, cancellation and completion fencing. Claim and publish in bounded database-only transactions; extraction and storage finish outside retry callbacks.

Locally use the existing polling runner. In cloud, invoke the same code through a bounded Cloud Run Job after durable enqueue; an invocation failure leaves the row retryable. Rehearse backlog draining and interrupted-worker recovery before launch.

**Acceptance criteria:** fake-clock/repository tests prove duplicate enqueue, exclusive claim, expiry/reclaim, stale completion rejection, bounded retries, poison-job failure, and cancellation; the same Alembic history serves local and cloud; chosen cloud strategy has a real-test requirement and documented cost implications.

**Out of scope:** general workflow engines, queue microservices, and cloud infrastructure provisioning.

### S2.6.2 — Integrate safe worker processing and progress UI

**Dependencies:** S2.6.1, S2.1.2.  
**Modules:** same-codebase worker, ingestion orchestration, job/import UI.

**Goal:** recover slow extraction without exposing incomplete financial records.

**Work:** run extraction/normalization/validation as bounded worker stages; persist stage outputs for retry; renew leases and fence writes; resume existing idempotent staging batches; require accepted review revision before commit; expose safe counts/status/errors and cancel/reprocess controls; add dry-run cleanup for orphaned unpublished revisions/files with reference/retention checks. Stage 1 has manual/cached quotes and upload-only fund formats, not live refresh services. Add scheduled quote/fund fetching only after the specific provider work and rights review; reuse existing deterministic import/selection code with cache, budgets and idempotency policies.

**Requirements:** database OCC retry never repeats OCR/AI/account fetches; any deliberate external retry is a separately recorded adapter attempt under its own policy. Cancellation before final publish preserves canonical data; after publication return committed state rather than claiming reversal.

Test parser timeouts, bounded retries, cancellation during work and stale-worker publication rejection. Cloud readiness additionally requires real execution/identity/private-object evidence; local tests do not establish it.

**Out of scope:** partial publication, cancellation that deletes accepted history, and unbounded cleanup.

### S2.6.3 — Evaluate and release the document-finance slice

**Dependencies:** S2.1.1–S2.4, S2.6.1–S2.6.2; S2.5 only if enabled.  
**Modules:** benchmarks, integration/browser tests, documentation.

**Goal:** prove that automation remains reviewable, accurate, and optional.

**Work:** run the synthetic brokerage + bank/card journey; compare deterministic/no-model extraction with shared extraction candidates; record exact numeric/date/identifier matches, row coverage, false matches/duplicates, reconciliation errors, review rate/correction effort, latency/resources; execute local and separately gated real Neon publication/job checks; document actual worker/parser/benchmark commands and fallback steps.

**Requirements:** record fixture/parser/schema/model/hardware versions. Critical numerical errors cannot pass through a model-quality average; they must be blocked/reviewed and rechecked outside the model. Unavailable optional binaries/providers are explicit skipped checks, not successful evaluations.

**Acceptance criteria:** clean local setup reviews and commits both statement types with models/sync disabled; reimport leaves totals unchanged; spending/holdings reconcile; failure/cancel/retry are safe; OCR benchmark and privacy results are recorded; every persistent/job change has real Neon evidence before cloud promotion.

**Out of scope:** introducing Stage 3 calculations to compensate for missing statement data, and treating benchmark success as permission to remove review.

## Stage 2 completion review

1. Do originals, extracted evidence, corrections, review approvals, and canonical records have a reconstructable lineage?
2. Can duplicate/reprocessed statements and interrupted workers recover without duplicate holdings/transactions?
3. Do bank/card imports, categories, splits, refunds, and transfers reconcile without double-counting?
4. Are totals/currencies/unparsed rows and missing financial coverage visible?
5. Do no-model/no-sync workflows function, with remote transmission blocked unless expressly permitted?
6. Are OCR/model results measured, with critical arithmetic independently validated?
7. Are jobs leased/fenced/idempotent and cloud behavior tested on the actual chosen implementation?

Only after local answers are yes should [Stage 3](stage-3-implementation-plan.md) rely on these records. Production adds the current real-Neon and [Stage 4](stage-4-implementation-plan.md) security gates.

**Implementation handoff:** record schema/client/parser versions, transaction sign/dedup and transfer policies, private-storage retention, review/cancel semantics, worker strategy, benchmark commands/results, optional connection review, and explicitly unverified cloud checks.


Provider-specific dated delivery facts are preserved in [the pre-migration snapshot](history/pre-gcp-neon/stage-2-implementation-plan.md). [ADR 0002](adr/0002-gcp-neon.md) and the [migration record](gcp-neon-migration.md) define the current architecture; this plan does not claim additional product completion.
