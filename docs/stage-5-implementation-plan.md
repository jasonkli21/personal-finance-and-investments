# Stage 5 implementation plan

**Status:** Proposed execution backlog, not implemented  
**Updated:** 2026-10-01  
**Roadmap coverage:** Work packages 5.1–5.6

This is the execution plan for source-grounded, portfolio-aware research. Read [the product specification](01-product-spec.md), [source policy](03-data-sources.md), [research/AI boundaries](04-ingestion-and-ai.md), [security](06-security-and-deployment.md), and [DSQL contract](07-aurora-dsql-compatibility.md) first. Research consumes the reliable [Stage 1 exposure contract](stage-1-implementation-plan.md); optional history/lots come from Stage 3 only if implemented. Hosted execution additionally requires [Stage 4](stage-4-implementation-plan.md).

## Scope boundary

Stage 5 adds public SEC EDGAR filings/XBRL facts and official IR documents, dated source-linked company views, user thesis/watchlist records, portable retrieval, optional structured cited summaries, and explicitly configured public-development monitoring.

The smallest vertical slice is **select a held company → retrieve permitted dated public filings → select traceable passages → display a dated cited summary alongside frozen actual/derived exposure → save a user-written thesis note**. Modules are `research`, public-data/model/search adapters, the `ResearchIndex` interface, portfolio read services, optional jobs, and web research views.

Research never mutates canonical holdings, quotes, prices, lots, or transactions. Autonomous trade recommendations/execution, uncited model news, paid-source dependency, paywall/authentication bypass, general web crawling, automatic thesis rewriting, vector infrastructure as a prerequisite, and speculative multi-agent orchestration are excluded.

## Delivery conventions and cross-cutting requirements

- Public observations, reported financial facts, selected evidence, model inferences, user thesis notes, and portfolio context are distinct data classes with explicit provenance.
- Use fixed bounded workflows first. Fetch/parse/model work occurs outside write transactions and database-only OCC retries reuse saved outputs.
- Research is opt-in and model/search-disabled behavior is useful: source documents, deterministic facts and cached exposure remain available.
- Remote public-data fetching does not authorize transmission of portfolio values, account/fund details, notes or watchlists to a cloud model/search service. Local model is the default optional inference path; remote requests require explicit provider/data review and minimized context consent.
- Reverify SEC/IR/search access rules, attribution, quotas, formats and provider terms when implementing. Source register check dates remain distinct from test execution dates.
- All factual citations link to actual selected document/passages; IDs alone or model-generated URLs do not prove support. Distinguish factual support from inference and uncertainty.
- Preserve filing accession, reported period, units, publication/filing/effective/retrieval dates, raw hashes and amendments. Never collapse restatements into an earlier observation invisibly.
- Exact financial calculations and portfolio exposure remain Decimal and deterministic. Models describe them but cannot create authoritative amounts or replace source facts.
- Start metadata/company/title/filing filters and bounded portable text matching behind `ResearchIndex`. No production dependency on pgvector, PostgreSQL extensions or assumed full-text parity.
- Research results freeze input evidence/context versions. Cached results become visibly stale under source-specific freshness rules; fetching now does not make an old filing current.

## Required verification matrix

| Area | Required fixtures / failure cases | Evidence |
| --- | --- | --- |
| Public source | Company/CIK mismatch, amendment, quota, no CORS browser path, malformed/oversize response | Offline adapter contracts; opt-in official-source smoke |
| Metrics | Units/currency, instant versus duration, fiscal period, overlapping/restated facts, missing denominator | Deterministic reconciliation fixtures |
| Retrieval | Wrong issuer, duplicates/conflicts, stale/missing dates, empty corpus, token/byte budget | Fake and portable-index tests |
| Citations | Invented source ID/URL, unsupported claim, false quotation, truncated passage | Validator tests and labelled evaluation report |
| Context/privacy | Direct/ETF exposure, account filters, stale baseline, sensitive notes, remote disabled | No canonical writes; blocked unauthorized egress |
| Model/search | Disabled/outage/invalid JSON/quota, unsafe URL/redirect, prompt injection | Fake-provider and safety bounds |
| Monitoring | Duplicate filings/reruns, amendment, unchanged state, lease loss/cancel, notification failure | Idempotent jobs and explicit notification policy |
| Persistence | Document/run/note schema, bounded writes, retries, immutable lineage | PG integration; actual DSQL before hosted promotion |
| Release journey | Company → cited summary/exposure → thesis; all APIs disabled | Browser smoke and deterministic offline fallback |

## Required implementation artifacts

**Required persisted records:**

| Record | Minimum fields / invariant |
| --- | --- |
| Research document | UUID, issuer/security/CIK, accession/type where applicable, title/URL, filing/publication/period dates nullable, retrieval time, content hash/private file key, parser/source version, status |
| Reported fact | Document/accession/source reference, taxonomy/concept, raw value/unit, Decimal normalized value when valid, currency, period start/end or instant, amendment/context, quality |
| Passage / evidence | Document/section/page reference, exact extracted text, content hash, offsets where supported, source/date/freshness state, extraction version |
| Research run | Issuer/user request scope, idempotency key, mode/state, frozen portfolio revision/context reference, query/source/evidence selections, budgets, policy/model versions, timestamps, safe failure |
| Research result | Run, generated time, structured facts/inferences/unknowns/conflicts, citations to selected passages, validation state, source freshness, portfolio context label |
| Thesis / watchlist | User-authored text/security/issuer, revisions/timestamps, source attachments if chosen; model text never silently replaces it |
| Monitor / notification receipt | Explicit issuer/event scope, cadence, last seen accession/hash, dedup key, enabled/status, delivery preference/outcome; no duplicate alerts on job retry |

**Required interfaces and routes:**

| Boundary | Behavior |
| --- | --- |
| `PublicDocumentProvider` / fact adapter | Bounded permitted SEC/IR observations with full source metadata |
| `ResearchIndex` | Ingest/reference, metadata/text query, bounded ranked passage selection and eligibility; portable implementation first |
| `StructuredModelProvider` | Local/fake/disabled and separately approved remote inference; schema/citation validation |
| Optional `SearchProvider` | Permitted bounded public search with attributable URLs/date metadata; no portfolio/account details in query |
| `GET /api/v1/research/companies/{id}` | Documents/facts/thesis/exposure context with independent source dates |
| `POST /api/v1/research/runs`, `GET /.../runs/{id}` | Explicit idempotent request, state/result/evidence or safe failure |
| `/api/v1/research/notes` and `/watchlists` | User-controlled create/edit/archive with revisions |
| Optional `/api/v1/research/monitors` | Explicit scope/cadence/notification settings, pause/cancel and status |

Finalize schema/methods/pagination in OpenAPI and refresh the generated TypeScript client. Include stable errors for disabled providers, insufficient evidence, stale context, unavailable source, exceeded budget and invalid citations.

**Configuration:** research/model/search enabled flags default safely off; provider/model allowlists; public fetch URL/rate/timeout/redirect/byte/concurrency limits; source-specific freshness; corpus/query/passage/context/output budgets; prompt/schema version; monitoring disabled until chosen; no automatic paid fallback. Local fixtures work without any model/search credentials.

## Dependency map

```text
Stage 1 exposure ─> S5.1.1 Fixtures/contracts ─> S5.1.2 Public sources ─> S5.2.1 Facts/UI
                          ├───────────────────> S5.3 Portfolio/thesis context
                          └─> S5.4 Retrieval <── S5.1.2
S5.2.1 + S5.3 + S5.4 ─> S5.2.2 Cited synthesis/UI ─> S5.6 Evaluation/release
S5.1.2 + existing Stage 2 job contract ─> S5.5 Optional monitoring ─> S5.6 if enabled
Stage 4 + applicable real DSQL research suite ────────────────────────> hosted gate
```

Neither optional tax/performance history nor cloud hosting is required for local research. Until the durable Stage 2 job contract is available, monitoring stays manual/disabled rather than adding a second untested queue design.

---

## Stage 5 — Portfolio-aware research and AI

### S5.1.1 — Establish research fixtures, contracts and baseline

**Dependencies:** Stage 1 completion and accepted research/privacy boundaries.  
**Modules:** research schemas, fixtures, fake providers/index/model.

**Goal:** define what a sourced report must prove before adding external calls.

**Work:**

1. Build synthetic and permission-cleared/public-company examples for filings, metric periods/units, amendments, conflicting/stale facts, unsupported claims, wrong issuer, and missing evidence.
2. Record a no-model baseline: selected dated source links, deterministic facts, and exact frozen portfolio exposure with no generated narrative.
3. Define document/fact/passage/run/result/thesis contracts, citation IDs/links, inference labels, freshness rules and idempotency identities.
4. Specify provider/index/model interfaces, context minimization, disabled modes, request budgets, safe failure states and repository read/write boundaries.
5. Prepare versioned schema/migrations and fixture schemas only for research records now needed; do not add speculative agent state.

**Requirements:** every generated factual claim has selected supporting evidence; user notes are context, not independently verified facts. Research cannot call canonical portfolio/tax write repositories.

**Acceptance criteria:** fixtures distinguish public fact, calculation, inference, user thesis and portfolio context; all contracts validate offline; baseline includes missing/stale evidence states; a remote disabled test sends no context; plans name concrete schema/API/index/config artifacts before adapter work.

**Out of scope:** multi-agent loops, trade ranking, trained recommendation policies, and assuming model knowledge is fresh evidence.

### S5.1.2 — Implement SEC/IR public-document ingestion

**Dependencies:** S5.1.1; current official access/format/terms verification.  
**Modules:** public source adapters, research repositories/private content store.

**Goal:** retrieve dated, traceable public observations for the correct issuer.

**Work:**

1. Implement conservative issuer/CIK mapping with reviewed identifiers; wrong/ambiguous matches remain unresolved.
2. Add backend SEC submissions/company-facts/filing retrieval with identified user-agent, cached responses, permitted access cadence, rate/time/byte bounds and safe failure classification.
3. Add a small allowlist of official company IR documents via permitted routes; validate URL schemes/host redirects and block local/private targets before any fetch.
4. Persist accession/filing/publication/period/retrieval dates, document hashes/URLs and exact extracted text/evidence; amendments remain distinct linked records.
5. Save originals in FileStore and bounded metadata in SQL; stage large evidence/fact batches idempotently, then publish completed document revisions.

**Requirements:** SEC fetches occur server-side under the documented CORS/access policy. Missing dates remain null, not guessed. A request returning HTML/error/another company's facts cannot publish valid evidence; DB retries reuse the fetched document.

**Acceptance criteria:** synthetic adapters cover valid filings, duplicate retrieval, amendment, wrong CIK, malformed payload, `Retry-After`, quota, timeout, unsafe redirects and oversized content; official opt-in smoke records attribution and current policy checks; published evidence retains source hashes/links without requiring live sites in CI.

**Out of scope:** broad crawling, authenticated/paywalled material, arbitrary user URL fetching without controls, and discarding restatement history.

### S5.2.1 — Normalize reported metrics and build sourced company views

**Dependencies:** S5.1.2.  
**Modules:** research facts/domain comparisons, company UI.

**Goal:** compare like reported periods and units without false precision.

**Work:**

1. Define explicit concept/unit/currency/period/context selection policies for a small useful set of reported company metrics.
2. Preserve all source observations; select/compare facts by issuer, taxonomy/concept, unit, instant/duration, fiscal period and amendment policy, exposing conflicts.
3. Implement Decimal period-over-period calculations only for comparable inputs; label missing/zero denominator, mismatched periods/units and restated values.
4. Build source-linked filing/metric tables with filing/period/retrieval dates and drill-through to exact source context.
5. If public-news search is added, verify one permitted provider's access/attribution/budget, isolate its adapter and keep unknown publication dates visible.

**Requirements:** retrieval date is not publication date; XBRL concept names alone do not establish comparability. Subjective model interpretation stays outside reported metric records. Search is optional, never a fallback to uncited news.

**Acceptance criteria:** fixtures prove valid comparisons, incompatible periods/units, amendments, duplicate contexts and missing denominator handling; company views retain original URLs/accessions; search-disabled UI still shows filings/facts; an outage retains cached data with stale disclosures.

**Out of scope:** full fundamental normalization across every industry, predictive scores, and replacing reported facts with AI estimates.

### S5.3 — Add frozen portfolio context and user thesis/watchlists

**Dependencies:** S5.1.1; Stage 1 portfolio/exposure services.  
**Modules:** research context service, notes/watchlists, portfolio read boundary.

**Goal:** relate public company material to actual ownership without leaking private context.

**Work:** retrieve dated direct and ETF-derived security/issuer exposure through existing read contracts; freeze account filters and position/quote/fund snapshot IDs for each run; attach separate company-report history if available; implement user-authored thesis/watchlist versioning with explicit edits; define local versus approved remote context bundles with privacy minimization.

**Requirements:** direct/derived exposure are labelled separately and never summed into extra net worth. Account labels/balances/notes are private; they do not enter public search queries or remote inference merely because filings are public. Thesis notes may guide a question but cannot be cited as external support.

**Acceptance criteria:** synthetic $35,200 NVDA exposure matches the selected portfolio baseline; changed positions create a new context rather than altering an old run; notes remain user-controlled; missing holdings/issuer mapping/history stay visible; privacy tests block unauthorized remote context; no canonical financial write occurs.

**Out of scope:** automatic thesis promotion/rewriting, inferred purchase history, and exposing account identifiers in telemetry.

### S5.4 — Implement portable, bounded passage retrieval

**Dependencies:** S5.1.1, S5.1.2.  
**Modules:** `ResearchIndex`, evidence selection, repository filters.

**Goal:** select attributable evidence without a production SQL-extension dependency.

**Work:**

1. Implement issuer/filing/type/date/title/section metadata filters and portable bounded text matching with deterministic relevance/tie-breaking.
2. Chunk extracted documents with retained section/source offsets; deduplicate exact content while preserving all document/source links and amendments.
3. Apply source-specific freshness, scope and attribution eligibility; retain material conflicts rather than selecting a single convenient story.
4. Select passages within configured count/byte/token budgets, recording selected/excluded IDs and reasons for reproducibility.
5. Measure a small corpus baseline before proposing semantic retrieval. Any local pgvector/full-text experiment stays behind the same interface and has a separately verified production alternative before adoption.

**Requirements:** bounded application matching cannot silently scan an unlimited corpus; no pgvector/GIN/tsvector production assumption. Source content is untrusted data and cannot issue tool/model instructions. Empty/expired corpus is a distinct insufficient-evidence outcome.

**Acceptance criteria:** correct-issuer passages rank predictably; duplicates retain provenance; unrelated issuer, stale/unattributed evidence and oversized context are excluded with reasons; conflicts survive selection; PG/DSQL portable implementation returns equivalent frozen selections; optional advanced index can be disabled without breaking research.

**Out of scope:** standalone vector database, learned ranking, general knowledge graph and autonomous iterative search.

### S5.2.2 — Synthesize and render validated cited research

**Dependencies:** S5.2.1, S5.3, S5.4; approved optional inference policy.  
**Modules:** research orchestration/model adapter/citation validator, run API/UI.

**Goal:** provide a dated research aid with inspectable factual support.

**Work:**

1. Create an idempotent run, freeze selected evidence/context and budgets, then call a fake/local structured model or return the deterministic no-model report.
2. Use versioned prompts/schemas that distinguish reported facts, calculations, inferences, conflicts and unknowns; treat document instructions as quoted data with no tool authority.
3. Validate citation IDs against selected evidence and URLs, quotation text against source passages, and factual support using fixture review/explicit claim checks; a resolvable link alone is insufficient.
4. Reject unsupported/invented claims or mark a safe insufficient result under the declared validation policy; never write model claims into reported facts or portfolio records.
5. Persist validated result and inference metadata, then render dated source links/excerpts, actual/derived exposure and uncertainty. Support recoverable outage/cancel/budget errors.

**Requirements:** model costs/content handling are allowed before calls, with no automatic paid/remote fallback. Database retry does not repeat synthesis. Private context stays local unless explicitly approved; model-generated URLs not present in selected evidence cannot become citations.

**Acceptance criteria:** fixtures reject nonexistent citation, invented quote, unsupported numerical claim and prompt injection; source conflicts/unknowns are visible; disabled/unavailable model returns useful linked sources/facts; repeated run request does not repeat provider calls invisibly; actual holdings/prices/lots remain unchanged.

**Out of scope:** tax/trade instructions, treating citations as proof of model correctness, and open-ended agent orchestration.

### S5.5 — Add optional public-development monitoring

**Dependencies:** S5.1.2; existing Stage 2 job lease/idempotency contract; S5.2.2 if summaries enabled.  
**Modules:** research monitors, same-codebase jobs, approved notification adapter.  
**Decision required:** issuer/event scope, cadence, retention and notification channel/preference.

**Goal:** detect meaningful new public evidence without duplicate work or unwanted alerts.

**Work:** persist explicit monitor configuration; schedule bounded source-appropriate public refresh; deduplicate by issuer/accession/content hash including amendments; save new research snapshots separately from old runs; notify only under the user's chosen policy; provide pause/cancel/status, failure backoff and delivery receipts; keep public monitoring queries free of private portfolio amounts/notes.

**Requirements:** scheduled refresh is opt-in, not implied by a one-time research request. Duplicate jobs cannot repeatedly fetch/infer/notify on unchanged data. Delivery failure is retried independently of source/model work; ambiguous send outcomes follow documented dedup semantics rather than a false exactly-once promise.

**Acceptance criteria:** unchanged source produces no repeat alert under change-only policy; new/amended filing is distinct; duplicate delivery/lease expiry/cancel/quota and notification failure preserve one saved observation/run and documented alert behavior; disabling jobs/notifications leaves on-demand research intact; provider and DSQL work budgets remain enforced.

**Out of scope:** trading alerts that imply recommendations, undeclared messaging channels, always-on cloud models, and new queue infrastructure outside the approved job/deployment track.

### S5.6 — Evaluate citation fidelity, privacy and disabled parity

**Dependencies:** S5.1.1–S5.4 and S5.2.2; S5.5 only when enabled.  
**Modules:** evaluation fixtures/reports, browser/integration tests, release docs.

**Goal:** prove source-grounded usefulness without making research authoritative financial state.

**Work:** run synthetic/public-company evaluation for citation resolution and semantic support, exact quotation traceability, period/unit accuracy, stale/irrelevant/conflicting sources, unsupported claims, prompt injection, privacy and outage; compare no-model baseline to configured local/approved models; execute company → cited report/exposure → user thesis journey; run PG persistence and separately real DSQL migrations/retrieval/idempotency/job cases before hosted promotion; document provider/model/policy/fixture versions and commands.

**Requirements:** report citation validity separately from claim support; perfect URLs cannot hide hallucinated claims. Distinguish deterministic CI from credentialed provider/cluster tests. Model/search-disabled parity includes existing holdings, imports, finance and simulations, not merely an error screen.

**Acceptance criteria:** dated company report links to accessible supporting sources and labels inferences/unknowns; stale/context gaps are visible; all canonical financial data remains unchanged; every model/search adapter can be disabled while core app and source views remain useful; prohibited egress/invalid citation/critical metric tests block release; actual live/cloud tests are recorded or explicitly unverified.

**Out of scope:** universal research accuracy claims, adopting paid advanced retrieval to conceal fixture failures, and promoting conclusions into facts without source review.

## Stage 5 completion review

1. Can a user choose a company and inspect dated accessible documents/facts before inference?
2. Do metrics preserve comparable units/periods, amendments and source context?
3. Does every factual claim have selected supporting evidence, with traceable quotations and visible conflicts?
4. Are actual holdings, derived exposure, thesis notes and model inferences distinct and frozen per run?
5. Does private context stay local unless its transmission is separately approved?
6. Does portable retrieval work without unverified DSQL SQL extensions?
7. Are optional monitors bounded/idempotent and governed by explicit notification preferences?
8. Does the complete app remain usable with all model/search APIs disabled, with hosted behavior gated on real DSQL/security tests?

**Implementation handoff:** publish routes/generated-client procedure, source/index/model contracts and settings, privacy/terms verification dates, corpus/freshness/context policies, citation/metric evaluation results, notification semantics, reproducible fixture commands, and local/provider/DSQL evidence separately.
