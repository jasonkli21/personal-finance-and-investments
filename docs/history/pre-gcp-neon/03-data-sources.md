> Historical snapshot at `4e5f3e3`, preserved 2026-10-03. Deployment guidance is superseded by [ADR 0002](../../adr/0002-gcp-neon.md). Do not use this snapshot as current instructions.

# Data sources and free-tier strategy

**Status:** Stage 1 upload-only issuer parsers implemented; Stage 5 SEC contract checked: 2026-10-03; other sources remain a research shortlist | **Provider pages checked:** 2026-09-25; Stage 1 issuer and Stage 3 tax sources checked: 2026-10-02; Stage 5 SEC sources checked: 2026-10-03; AWS/DSQL runtime and pricing checked: 2026-10-02
**Rule:** Prices, download shapes, terms of use, eligibility and quotas change. Reverify the official page before implementing or deploying a connector. Links here are evidence of published availability, **not** permission to scrape, redistribute, or automate a download.

## 1. Source-selection policy

For each provider, implement a separate adapter exposing: `provider_id`, stable source URL, instrument/identifier mapping, reporting `as_of`, `fetched_at`, parsed data, quality flags, retry policy, and raw response or content hash. Record credentials and usage limits outside source control. Prefer official issuer disclosures and authenticated user exports over unofficial scraping. Keep CSV/manual fallback for every external integration.

**Reliability order for personally held positions:** confirmed manual entry / user-uploaded brokerage export; optional consented account API; PDFs/OCR after review. Do not let ETF look-through material create actual user positions or tax lots.

## 2. ETF constituent portfolios — Stage 1 priority

| Provider | Published evidence | Proposed handling | Important caveat |
| --- | --- | --- | --- |
| **BlackRock iShares** | [IVV official fund page](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf-ivv): downloadable holdings CSV, effective date, ticker, weight, CUSIP/ISIN | Build one issuer adapter for 1–2 popular funds; snapshot and parse available full holdings | Export links/formats and permitted automated retrieval may change. Prefer official download or user-provided CSV. |
| **State Street SPDR** | [SPY official fund page](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy): daily full-holdings download | Second issuer adapter after iShares | Distinguish **fund holdings** from displayed **index holdings**. Verify terms and data date. |
| **Vanguard** | [VOO official advisor page](https://advisors.vanguard.com/investments/products/voo/vanguard-sp-500-etf): *Export full holdings* and dated portfolio details, historically monthly | Third adapter or manual portfolio-composition export; don't assume daily data | Some exports may depend on page/client behavior; verify intended personal-use access. |
| **Invesco QQQ** | [Invesco QQQ](https://www.invesco.com/qqq-etf/en/home.html) | Evaluate after the first three; manual full-holdings file acceptable | Confirm currently offered machine-readable **full** holdings and access terms at implementation time; top-ten is insufficient for look-through. |
| **US SEC Form N-PORT** | [Public N-PORT datasets](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets) | Longer-term regulatory fallback and historical validation | Public datasets are published quarterly; may include lagged information, huge files and complex asset definitions. **Not a substitute for current issuer daily portfolios**. |
| **User upload** | Brokerage/fund issuer CSV or XLSX supplied by the user | Mandatory Stage 1 fallback | Persist user-provided as-of date; avoid claiming provenance is issuer-verified. |

**Issuer onboarding checklist:** verify full constituents (not top holdings), effective date, fund vs index, identifiers, cash/derivatives, total reported weights, file format, usage restrictions, user-agent/rate expectations, reproducible parser fixture, changed-format detection, and independent source-link visibility in UI. Unsupported funds remain opaque, not excluded from net worth.

**MVP scope:** a small allowlist of supported ETF symbols; two official issuer adapters + manual CSV is sufficient to finish Stage 1. Source expansion should follow actual user holdings, not raw number of supported funds.

## 3. Quotes, prices and FX

| Candidate | Free/usage facts as checked | Default decision |
| --- | --- | --- |
| **Manual position or quote price** | No vendor quota; clearly dated | **Mandatory offline fallback**; label as manually supplied, not live |
| **Alpha Vantage** | [Official support page](https://www.alphavantage.co/support/) publishes 25 free API requests/day for most datasets; US real-time and 15-minute-delayed data are premium-only | Optional first API for small portfolios; batch/cache; never advertise real-time prices |
| **Brokerage statement prices** | As-of-statement historical snapshot values | Useful for initial import, not continuous quotes |
| **User CSV** | End-of-day prices/FX manually exported | Reliable fallback when the free quote budget is insufficient |
| **Yahoo/yfinance and other unofficial sources** | May be convenient, but API access, stability, and data rights may be unofficial or conditional | Research-only experiment if vetted; **not the sole production price dependency** |

**Policy:** cache quotes by security, provider, and timestamp. Display market-close/as-of timestamps. On provider outage, serve last-known values as *stale*, allow manual update, and exclude unpriced positions from a falsely precise percentage unless user approves a transparent approximation. Start USD-only in calculations if necessary; retain original foreign-currency metadata for later FX support.

## 4. Brokerage / bank connections — optional Stage 2

**Plaid**

- [Official Trial vs Sandbox policy](https://plaid.com/docs/account/billing/): for eligible **new US/Canada developer teams created on/after April 15, 2026**, Trial includes access to real production data for up to **10 lifetime Production Items**. Deleting an Item does **not** return a slot. Eligibility and institution support vary; legacy teams have different paths.
- Trial-listed products include [Investments](https://plaid.com/docs/investments/), Transactions, Balance, Statements and others; Sandbox uses mock data and is free.
- [Investments API reference](https://plaid.com/docs/api/products/investments/): position quantity/value and nullable aggregate `cost_basis`; `tax_lots` are present **only when the institution provides them**, and an empty array means lot data unavailable. Coverage varies by institution.
- [Plaid billing](https://plaid.com/docs/account/billing/): upgrading may introduce recurring per-Item fees for products such as Investments or Transactions. Check approved feature scope/fees before activating production or requesting refreshes.

**MVP alternative:** do **not** block local Stage 1 or Stage 2 on Plaid approval. Manual entry + CSV/PDF import must remain first-class. Never scrape credential-protected brokerage sites or store online-banking credentials directly.

## 5. Company financials and regulatory research — Stage 5

**SEC EDGAR** — [Official API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). Public, keyless `data.sec.gov` endpoints include company filing submissions and XBRL `companyfacts`/`companyconcept` JSON. SEC explicitly notes that `data.sec.gov` **does not support CORS**, so retrieve from Python backend, not the SPA. Identify the app in `User-Agent`, follow SEC fair-access guidelines, cache results, and favor SEC bulk archives when doing large-scale work. [SEC access policy](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) and [N-PORT data](https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets).

The SEC provides documents and standardized reported facts, not a fully normalized investment-research narrative. Record accession number, filing date, publication/retrieval time, CIK and original URL. Corrections/re-filings must not be silently merged into old facts.

**Shared research sourcing:** generic SEC/IR document research, search and evidence acquisition belong in `personal-ai-system`; finance-specific deterministic reported-fact adapters may remain here when a bounded need is demonstrated. Retain source dates/rights in finance results and reverify before use. Do not build a duplicate finance search runtime.

**Optional web search (upstream candidates):** [Tavily pricing](https://www.tavily.com/pricing) or [Brave Search API pricing](https://brave.com/search/api/). Evaluate whichever currently offers a viable no-cost quota. Do not assume either quota is permanent; do not make uncited model knowledge the source of financial news. Record full source URL, retrieval time and publication date when available.

**Other possible sources:** official company IR pages, corporate earnings releases, user-supplied reports and publicly licensed datasets; each gets a separate provenance tag and rights review.

**Stage 5 official SEC check — 2026-10-03:** The SEC's [EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) confirms public JSON submissions and XBRL `companyfacts` endpoints on `data.sec.gov`; those data endpoints require no API key, do not support browser CORS, and are republished in bulk ZIP archives nightly. SEC [access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) requires a descriptive `User-Agent`; the SEC [privacy/security policy](https://www.sec.gov/files/privacy.htm) caps aggregate automated access at 10 requests per second. These pages permit no assumption about source correctness, issuer-to-catalog identity, broad redistribution, or permission to download arbitrary linked filing content. Finance Stage 5 currently stores only SEC references and manually entered facts marked unverified; it makes no SEC requests, does not download filing bodies, and does not support IR sources. Any future SEC fetcher must run server-side, declare its user agent, obey the cap, retain accession/period/amendment lineage, and stay behind the reviewed source policy. Generic document retrieval remains upstream in personal-AI.

## 6. Shared AI service and upstream inference candidates — Stage 2 and Stage 5

Finance integrates reusable AI capabilities through `PersonalAIClient` to `personal-ai-system`. The service owns model SDKs, selection/routing, generic extraction, research/search and memory; do not implement the provider shortlist below as finance adapters. It is historical evaluation context (checked 2026-09-25), not a chosen or newly verified integration. No live service transport is implemented; Stage 1 runs independently. Before later activation, verify the actual upstream contract, provider costs/data-use, user consent, service authorization, verified owner propagation and logging/retention policy. Public upstream bootstrap with a fixed `local` owner is insufficient. See [ADR 0001](adr/0001-shared-personal-ai.md).

| Provider | Role | Free-first and privacy note |
| --- | --- | --- |
| **Ollama (local)** | Possible upstream local model for extraction and research | Zero API fee, consumes local CPU/RAM/GPU. [Schema-constrained JSON](https://docs.ollama.com/capabilities/structured-outputs). Verify local model license and hardware fit. |
| **GroqCloud** | Optional fast remote text inference for *non-sensitive* or consented content | [Official free-plan limits](https://console.groq.com/docs/rate-limits) vary **per model** and may change; enforce model allowlist, budgets and backoff. Review [privacy policies](https://groq.com/privacy-policy/). |
| **Google Gemini API** | Optional document/image experiments on synthetic or thoroughly redacted data | [Official pricing](https://ai.google.dev/gemini-api/docs/pricing) and [terms](https://ai.google.dev/gemini-api/terms). **Unpaid-tier submissions may be used to improve Google products and reviewed by humans; do not send real personal statements.** Paid-service data terms differ, but paid use is not the default. |
| **OpenRouter / Cloudflare Workers AI** | Optional future model comparison or cloud inference | Verify current free eligible models, rate/compute limits, retention, and third-party routing before use. No essential feature should depend on them. |

**Never** treat a consumer chatbot subscription as free application API credits. No cloud model is needed for basic manual/CSV Stage 1 portfolio tracking.

## 7. Data lineage and freshness contract

Every external observation stores:

```text
provider_id, source_url, retrieved_at, effective_as_of,
source_format, import_job_id, parse_version, raw_hash,
validation_status, errors_or_warnings, manual_override_if_any
```

Data display rules:

- **Freshness:** explicit as-of and fetched times, with per-source configurable stale thresholds (do not assign one threshold to all issuers).
- **Completeness:** show percent of holdings weight recognized and percent of portfolio NAV attributed; unknown/derivative/cash residuals are real output categories.
- **Conflicts:** if two sources disagree on a security or price, retain both observations and expose the selected precedence; do not overwrite the underlying raw records.
- **Failure:** backoff on rate limits; respect `Retry-After`; avoid repeated retries of user-auth/permission failures. Stale cached/manual data remains usable offline.
- **Currency:** do not aggregate foreign currencies without an as-of FX rate; preserve unmatched data for review.

## 8. Cost policy

- Stage 0–1 must succeed with **$0 external service spend** and no mandatory signup; local hardware/electricity excluded.
- External free tiers are **optional accelerators**, not hard dependencies; track calls/tokens/items in-app if connected.
- For future finance provider integrations, paid use stays explicitly disabled by default. Personal-AI must enforce its own model/provider budgets and prohibit silent paid fallbacks; finance checks the agreed policy before sending content. `PERSONAL_AI_ENABLED=false` is the current finance gate and true is rejected; no model-budget settings are implemented here yet.
- Record date of last cost/terms verification in each adapter's documentation; re-check before any cloud deployment, high-volume refresh or subscription activation.
## 9. Aurora DSQL as production structured-data store (not an external market-data provider)

- **Local PostgreSQL 16 is always available** with manual/CSV data and cached ETF snapshots. Production uses Aurora DSQL with the same source adapters; moving to AWS does not magically grant new market-data rights, data freshness or account access.
- [Official Aurora DSQL pricing](https://aws.amazon.com/rds/aurora/dsql/pricing/) (verified 2026-10-03): the published monthly free tier is **100,000 DPUs + 1 GB-month storage**; usage beyond it is billable. Other AWS services (compute, S3, CloudFront, AWS Backup, network endpoints, logging) can cost money. The account/organization's eligibility and total-stack costs require confirmation before provisioning. Track **per-source refreshes as potential database DPU consumption**, not merely HTTP API quotas.
- Retain bounded structured snapshots in DSQL, and put raw issuer holdings downloads, brokerage statement PDFs, screenshot images and archive exports in **private S3**. Avoid storing megabyte-scale raw provider JSON in DSQL. Use immutable provenance hashes and S3 object keys in the database.
- Optimize polling/refresh schedules with as-of-aware conditional downloads and cache hits; refreshing the same ETF every minute creates cost without improving a daily holdings snapshot.
- See [`07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md) for write batching, search restrictions, and DSQL test requirements.

**Stage 4 implementation check, 2026-10-02:** AWS's current [DSQL quota/transaction documentation](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/CHAP_quotas.html) was checked for transaction/connection ceilings; the DSQL-compatible engine continues to use the official [AWS SQLAlchemy dialect](https://pypi.org/project/aurora-dsql-sqlalchemy/) and [Python connector](https://pypi.org/project/aurora-dsql-python-connector/) with IAM token-on-connect and TLS hostname verification. The lock currently pins dialect 1.3.0 and connector 0.2.7. For private originals, S3 [conditional `PutObject`](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html) supports `If-None-Match` to reject replacement of an existing content key, and [server-side encryption](https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingServerSideEncryption.html) supports explicit SSE-S3 or SSE-KMS. These official feature references do not replace live IAM, bucket-policy, region, cost, or recovery verification for the operator's account.

**Stage 4 AWS cost check, 2026-10-03:** Current official pages were rechecked for [DSQL allowance and metering](https://aws.amazon.com/rds/aurora/dsql/pricing/), [App Runner provisioned/active compute](https://aws.amazon.com/apprunner/pricing/), [S3 storage/request/transfer components](https://aws.amazon.com/s3/pricing/), [ECR image storage](https://aws.amazon.com/ecr/pricing/), [CloudFront edge/request charges](https://aws.amazon.com/cloudfront/pricing/), [Secrets Manager](https://aws.amazon.com/secrets-manager/pricing/), and [AWS Budgets](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/). The DSQL page publishes a monthly allowance of 100,000 DPUs and 1 GB-month, with billable usage beyond it; it does not establish that the rest of the stack is free. Prices vary by service, Region, and account. App Runner includes provisioned memory and active compute; S3 and CloudFront usage depends on storage, requests, and geographic egress. AWS Budget alerts may lag and do not cap spending. See the dated [Stage 4 cost register](stage-4-cost-register.md); its unit examples are not an account-specific whole-stack forecast.

**Stage 4 runtime availability check, 2026-10-03:** AWS's [App Runner availability notice](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html) states that the service stopped accepting new customers on 2026-03-31; existing customers may continue. The selected prepared API topology therefore requires the operator to confirm the target account is eligible before enabling its App Runner resource. If it is not, Stage 4 needs a separately reviewed runtime choice and a fresh cost estimate; this project does not infer eligibility or silently substitute a service.

## Stage 1 issuer verification — 2026-10-02

The implemented adapters parse user-selected official downloads locally; they make no automated network requests. The file retains user-provided provenance even when its format matches an issuer. No credentials or fees are required by the local importer. Live network refresh is disabled with an actionable download/upload message; cached accepted compositions remain usable. Format tests use wholly synthetic data, not redistributed issuer holdings.

| Adapter | Current official evidence / shape | Rights, cadence and fallback |
| --- | --- | --- |
| iShares IVV | [Official fund page](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf) links [full CSV](https://www.ishares.com/us/products/239726/ishares-core-s-p-500-etf/latest-holdings.csv). Inspected metadata contains fund title, `Fund Holdings as of`, then Ticker/Name/Asset Class/Weight (%)/Exchange and a blank separator before footnotes. Effective date and full file matter; page NAV date is not substituted. | Current download shape inspected 2026-10-02. Automated access and redistribution permission have not been established, so upload-only; no guessed rate allowance. Check the issuer page when obtaining each file, retain its original date and raw rows. |
| State Street SPDR SPY | [Official SPY page](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy) separately labels Fund and Index holdings. Fund “Download All Holdings: Daily” links [Excel workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-spy.xlsx). Workbook metadata: Fund Name, Ticker Symbol, Holdings (`As of DD-Mon-YYYY`); table: Name/Ticker/Identifier/SEDOL/Weight/Sector/Shares Held/Local Currency. Weight is percent points; XML numeric text is read directly as Decimal, never through a float. | Shape inspected 2026-10-02; official page restricts copying/disclosure to third parties without consent. No issuer data is committed or redistributed. Personal local user upload is the fallback, subject to the user's source rights; automatic retrieval remains disabled. No credentials or automated quota assumed. |

These are two deterministic official-format parsers plus the generic CSV mapper, not claims of issuer authentication or live-fetch success. Unknown classes, cash, zero/negative weights and unsupported instruments remain evidence. Signed/leverage/overweight funds use whole-fund opaque exposure, and SPDR unsupported instrument rows remain other unless reviewed. Staleness is an application setting, independent of the provider's stated daily publication cadence. Wrong fund/date or changed required headers fail safely without altering last accepted history.

## Stage 3 U.S. federal tax-policy verification — 2026-10-02

The hypothetical lot-sale feature records policy version `us-federal-pub550-2025-holding-period-wash-sale-v1`. Its limited ordinary holding-period candidate and potential same-security acquisition screen were checked against the [IRS Publication 550 for 2025](https://www.irs.gov/publications/p550) on 2026-10-02. Publication 550 describes long-term treatment for property held more than one year, with the holding period starting the day after acquisition and the disposition date included. Missing acquisition dates and leap-day anniversary cases remain unknown; the application does not model special acquisition histories, gifts, inheritance, prior-period tacking, or exceptions.

Publication 550's wash-sale discussion covers a loss disposition and acquisition of substantially identical securities within 30 days before or after. The feature does not decide legal identity: it only flags matching records with the same local `security_id`, using reviewed positive buy events and recorded tax-lot acquisition dates in its 61-day inclusive window. This is a screening hint, not an application of the legal “substantially identical” standard. The [IRS 2026 Instructions for Form 1099-B](https://www.irs.gov/instructions/i1099b) also describe a narrower broker-reporting case based on same-CUSIP covered securities in the same account, and note that brokers may report across separate accounts. That reporting rule is not treated as complete household coverage.

Every warning reports coverage as unknown, includes its source record dates/account labels, and says that no detected match is not compliance clearance. Records outside this application, spouse activity, options, and unrepresented accounts or securities are not observed. No rate or tax-liability estimate is calculated. These policies are limited to a U.S. federal educational estimate and are not tax advice or filing support.
