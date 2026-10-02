# Stage 5 implementation plan

**Status:** Proposed execution backlog, not implemented  
**Updated:** 2026-10-02
**Roadmap coverage:** Work packages 5.1–5.6

This is the execution plan for source-grounded, portfolio-aware research. Read [the product specification](01-product-spec.md), [source policy](03-data-sources.md), [research/AI boundaries](04-ingestion-and-ai.md), [security](06-security-and-deployment.md), and [DSQL contract](07-aurora-dsql-compatibility.md) first. Research consumes the reliable [Stage 1 exposure contract](stage-1-implementation-plan.md); optional history/lots come from Stage 3 only if implemented. Hosted execution additionally requires [Stage 4](stage-4-implementation-plan.md).

## Scope boundary

Stage 5 adds finance-facing SEC/IR source/fact views, user thesis/watchlist records, optional cited research via `PersonalAIClient` and explicitly configured public-development monitoring. Generic document research ingestion, search, retrieval/indexing/ranking, evidence lifecycle, model synthesis and AI memory belong in `personal-ai-system` per [ADR 0001](adr/0001-shared-personal-ai.md). Finance validates issuer/period/unit/citations, retains needed dated result/source snapshots and owns product workflows.

The smallest vertical slice is **select a held company → retrieve permitted dated public filings → select traceable passages → display a dated cited summary alongside frozen actual/derived exposure → save a user-written thesis note**. Modules are finance `research` validation/result/context services, `PersonalAIClient`, portfolio reads, optional finance jobs and web views. Do not add generic model/search/index adapters here.

Research never mutates canonical holdings, quotes, prices, lots, or transactions. Autonomous trade recommendations/execution, uncited model news, paid-source dependency, paywall/authentication bypass, general web crawling, automatic thesis rewriting, vector infrastructure as a prerequisite, and speculative multi-agent orchestration are excluded.

## Delivery conventions and cross-cutting requirements

- Public observations, reported financial facts, selected evidence, model inferences, user thesis notes, and portfolio context are distinct data classes with explicit provenance.
- Use fixed bounded workflows first. Fetch/parse/model work occurs outside write transactions and database-only OCC retries reuse saved outputs.
- Research is opt-in and model/search-disabled behavior is useful: source documents, deterministic facts and cached exposure remain available.
- Remote public-data fetching does not authorize transmission of portfolio values, account/fund details, notes or watchlists to a cloud model/search service. The shared service controls allowed local/cloud inference. Any transmitted context requires scoped consent/data-handling review; deployed private context additionally requires verified user/service/owner authorization. The fixed `local` owner is insufficient.
- Reverify SEC/IR/search access rules, attribution, quotas, formats and provider terms when implementing. Source register check dates remain distinct from test execution dates.
- All factual citations link to actual selected document/passages; IDs alone or model-generated URLs do not prove support. Distinguish factual support from inference and uncertainty.
- Preserve filing accession, reported period, units, publication/filing/effective/retrieval dates, raw hashes and amendments. Never collapse restatements into an earlier observation invisibly.
- Exact financial calculations and portfolio exposure remain Decimal and deterministic. Models describe them but cannot create authoritative amounts or replace source facts.
- Request bounded issuer/filing/date/source eligibility through the shared research contract and validate returned references/freshness. Do not create a finance `ResearchIndex`, vector store or generic retrieval runtime; finance SQL has no pgvector/full-text dependency.
- Research results freeze input evidence/context versions. Cached results become visibly stale under source-specific freshness rules; fetching now does not make an old filing current.

## Required verification matrix

| Area | Required fixtures / failure cases | Evidence |
| --- | --- | --- |
| Public source | Company/CIK mismatch, amendment, quota, no CORS browser path, malformed/oversize response | Offline adapter contracts; opt-in official-source smoke |
| Metrics | Units/currency, instant versus duration, fiscal period, overlapping/restated facts, missing denominator | Deterministic reconciliation fixtures |
| Retrieval | Wrong issuer, duplicates/conflicts, stale/missing dates, empty corpus, token/byte budget | Fake personal-AI contracts and finance provenance checks |
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
| Returned evidence reference/snapshot | Upstream evidence/run ID, source URL/date/hash and approved excerpt/offset when needed for finance citation validation; generic evidence store/index remains upstream |
| Research run | Issuer/user request scope, idempotency key, mode/state, frozen portfolio revision/context reference, query/source/evidence selections, budgets, policy/model versions, timestamps, safe failure |
| Research result | Run, generated time, structured facts/inferences/unknowns/conflicts, citations to selected passages, validation state, source freshness, portfolio context label |
| Thesis / watchlist | User-authored text/security/issuer, revisions/timestamps, source attachments if chosen; model text never silently replaces it |
| Monitor / notification receipt | Explicit issuer/event scope, cadence, last seen accession/hash, dedup key, enabled/status, delivery preference/outcome; no duplicate alerts on job retry |

**Required interfaces and routes:**

| Boundary | Behavior |
| --- | --- |
| `PersonalAIClient` research capability (later) | Versioned bounded request/result/source evidence; fake/disabled behavior; shared search/retrieval/synthesis stays upstream |
| Finance result/fact validator | Source/issuer/date/citation checks; deterministic metric normalization and comparison; no generic evidence index |
| Optional finance-specific fact adapter | Only if necessary for deterministic reported facts; current rights/format checks, no duplicate research crawler |
| `GET /api/v1/research/companies/{id}` | Documents/facts/thesis/exposure context with independent source dates |
| `POST /api/v1/research/runs`, `GET /.../runs/{id}` | Explicit idempotent request, state/result/evidence or safe failure |
| `/api/v1/research/notes` and `/watchlists` | User-controlled create/edit/archive with revisions |
| Optional `/api/v1/research/monitors` | Explicit scope/cadence/notification settings, pause/cancel and status |

Finalize schema/methods/pagination in OpenAPI and refresh the generated TypeScript client. Include stable errors for disabled providers, insufficient evidence, stale context, unavailable source, exceeded budget and invalid citations.

**Configuration:** finance personal-AI/research and monitoring gates default off; bounded approved service URL/timeout/redirect/request/response limits, verified identity and scoped consent, source freshness, context/output budgets and schema version. Upstream owns model/search allowlists, generic prompt/index/corpus/runtime limits and provider credentials; finance checks its agreed no-paid-fallback policy. Local fixtures require no live service or model credentials. Current Stage 1 enablement remains rejected.

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
**Modules:** research schemas, fixtures, fake personal-AI client and finance result validators.

**Goal:** define what a sourced report must prove before adding external calls.

**Work:**

1. Build synthetic and permission-cleared/public-company examples for filings, metric periods/units, amendments, conflicting/stale facts, unsupported claims, wrong issuer, and missing evidence.
2. Record a no-model baseline: selected dated source links, deterministic facts, and exact frozen portfolio exposure with no generated narrative.
3. Define document/fact/passage/run/result/thesis contracts, citation IDs/links, inference labels, freshness rules and idempotency identities.
4. Agree a bounded versioned personal-AI research capability and finance DTOs; specify context minimization, identity/consent, disabled modes, budgets, safe errors and finance read/write boundaries. Do not assume the handoff examples match the current upstream API.
5. Prepare versioned schema/migrations and fixture schemas only for research records now needed; do not add speculative agent state.

**Requirements:** every generated factual claim has selected supporting evidence; user notes are context, not independently verified facts. Research cannot call canonical portfolio/tax write repositories.

**Acceptance criteria:** fixtures distinguish public fact, calculation, inference, user thesis and portfolio context; all contracts validate offline; baseline includes missing/stale evidence states; a remote disabled test sends no context; plans name concrete finance schema/API/service/config artifacts before adapter work.

**Out of scope:** multi-agent loops, trade ranking, trained recommendation policies, and assuming model knowledge is fresh evidence.

### S5.1.2 — Integrate dated shared SEC/IR observations

**Dependencies:** S5.1.1; upstream capability availability and current source/rights/contract review.
**Modules:** personal-AI adapter, finance source references/result validation, private result storage.

**Goal:** obtain traceable public observations for the correct issuer without a second research pipeline.

**Work:** agree upstream company/CIK/filing/evidence contracts; request bounded dated SEC/IR observations through the service; validate issuer/accession/URL/date/hash/amendment metadata in finance; retain needed immutable reference/result snapshots in bounded SQL/private artifacts. Share databases or object storage with neither project. Generic fetch/cache/extraction/evidence ingestion belongs upstream. Add a finance-specific deterministic XBRL fact adapter only if shared results cannot satisfy a demonstrated finance calculation need; verify official source policy and document that exception.

**Requirements:** fetched evidence is not canonical portfolio data. Missing dates stay null, amendments remain distinct and DB retry reuses external outputs. No source/provider cost or live capability claims from synthetic fixtures. Preserve finance source lineage even though generic evidence infrastructure is upstream.

**Acceptance criteria:** fake service contracts cover duplicate/amended/wrong-company/malformed/oversize/timeout/quota results and disabled fallback; bad references cannot publish a valid finance result. Actual upstream/source smoke is separately opt-in and labelled unverified until run.

**Out of scope:** generic research crawler/index/evidence runtime in finance, broad crawling, auth/paywall bypass and shared persistence.

### S5.2.1 — Normalize reported metrics and build sourced company views

**Dependencies:** S5.1.2.  
**Modules:** research facts/domain comparisons, company UI.

**Goal:** compare like reported periods and units without false precision.

**Work:**

1. Define explicit concept/unit/currency/period/context selection policies for a small useful set of reported company metrics.
2. Preserve all source observations; select/compare facts by issuer, taxonomy/concept, unit, instant/duration, fiscal period and amendment policy, exposing conflicts.
3. Implement Decimal period-over-period calculations only for comparable inputs; label missing/zero denominator, mismatched periods/units and restated values.
4. Build source-linked filing/metric tables with filing/period/retrieval dates and drill-through to exact source context.
5. If public-news search is used, consume the shared service's attributable observations under reviewed access/budget policy; keep unknown publication dates visible without a finance search-provider adapter.

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

### S5.4 — Agree shared retrieval eligibility and validate evidence

**Dependencies:** S5.1.1, S5.1.2; actual upstream research capability.
**Modules:** finance service request builders and evidence/result validators.

**Goal:** obtain attributable, bounded evidence without duplicating indexing/retrieval.

**Work:** specify company/issuer/filing/date/source scope and count/byte/context limits in the agreed service contract; personal-AI performs chunking, matching/ranking, indexing and evidence lifecycle. Finance checks returned source identity, dates/freshness, traceable excerpts/offsets and scope; preserve conflicts and freeze returned evidence/run references with result snapshots. Source content remains untrusted and cannot grant tool authority. Empty/unavailable/expired evidence is an explicit outcome.

**Requirements:** no finance-owned `ResearchIndex`, embeddings, vector database or SQL-extension dependency. Finance's retained source references and citation checks complement upstream provenance; they are not a second generic evidence engine.

**Acceptance criteria:** fake/HTTP contract fixtures reject wrong issuer, stale/out-of-scope/unattributed/nontraceable excerpts and oversized results; conflicts and insufficient evidence remain visible. Finance PG/DSQL result persistence is tested independently of upstream index storage. Cached/manual company views work when the service is disabled.

**Out of scope:** rebuilding shared chunking/ranking/retrieval, local pgvector experiments in this repo, general knowledge graphs and autonomous search loops.

### S5.2.2 — Synthesize and render validated cited research

**Dependencies:** S5.2.1, S5.3, S5.4; approved optional inference policy.  
**Modules:** finance research workflow, personal-AI adapter and citation validator, run API/UI.

**Goal:** provide a dated research aid with inspectable factual support.

**Work:**

1. Create an idempotent finance run, freeze source/context versions and budgets, then call the shared service through a fake/approved adapter or return the deterministic cached/manual report. Verify identity and consent before any private context leaves finance.
2. Use versioned finance DTOs that distinguish facts, calculations, inferences, conflicts and unknowns; generic prompts/synthesis run upstream. Treat document instructions as untrusted data with no finance tool authority.
3. Validate citation IDs against selected evidence and URLs, quotation text against source passages, and factual support using fixture review/explicit claim checks; a resolvable link alone is insufficient.
4. Reject unsupported/invented claims or mark a safe insufficient result under the declared validation policy; never write model claims into reported facts or portfolio records.
5. Persist validated result and inference metadata, then render dated source links/excerpts, finance-computed actual/derived exposure and uncertainty. Support recoverable outage/cancel/budget errors.

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

**Work:** run synthetic/public-company evaluation for citation resolution and semantic support, exact quotation traceability, period/unit accuracy, stale/irrelevant/conflicting sources, unsupported claims, prompt injection, privacy and outage; compare deterministic finance baseline to shared research results; reuse upstream generic-model evaluation evidence; execute company → cited report/exposure → user thesis journey; run PG finance-result persistence and separately real DSQL migrations/idempotency/job cases before hosted promotion; document provider/model/policy/fixture versions and commands.

**Requirements:** report citation validity separately from claim support; perfect URLs cannot hide hallucinated claims. Distinguish deterministic CI from credentialed provider/cluster tests. Model/search-disabled parity includes existing holdings, imports, finance and simulations, not merely an error screen.

**Acceptance criteria:** dated company report links to accessible supporting sources and labels inferences/unknowns; stale/context gaps are visible; all canonical financial data remains unchanged; the shared service can be disabled while core app and source views remain useful; prohibited egress/invalid citation/critical metric tests block release; actual live/cloud tests are recorded or explicitly unverified.

**Out of scope:** universal research accuracy claims, adopting paid advanced retrieval to conceal fixture failures, and promoting conclusions into facts without source review.

## Stage 5 completion review

1. Can a user choose a company and inspect dated accessible documents/facts before inference?
2. Do metrics preserve comparable units/periods, amendments and source context?
3. Does every factual claim have selected supporting evidence, with traceable quotations and visible conflicts?
4. Are actual holdings, derived exposure, thesis notes and model inferences distinct and frozen per run?
5. Does private context stay local unless its transmission is separately approved?
6. Does shared retrieval satisfy scope/provenance bounds without finance SQL-extension or duplicate-index dependencies?
7. Are optional monitors bounded/idempotent and governed by explicit notification preferences?
8. Does the complete app remain usable with all model/search APIs disabled, with hosted behavior gated on real DSQL/security tests?

**Implementation handoff:** publish routes/generated-client procedure, source/service/result contracts and settings, privacy/terms verification dates, corpus/freshness/context policies, citation/metric evaluation results, notification semantics, reproducible fixture commands, and local/provider/DSQL evidence separately.
