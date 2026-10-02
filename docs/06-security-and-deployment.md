# Security, privacy, portability and AWS deployment

**Status:** Local Stage 1 controls implemented; cloud/AI launch gates planned | **Updated:** 2026-10-02
**Deployment strategy:** PostgreSQL 16 runs locally indefinitely. Cloud deployment is optional in timing, but **Aurora DSQL is mandatory for production**. Its recurring database allowance is not a promise of free total cloud hosting. See [`07-aurora-dsql-compatibility.md`](07-aurora-dsql-compatibility.md).

## 1. Threat model and scope

The app may hold account identifiers, positions, investments, statements, credit-card transactions and tax lots. Major risks include unintended cloud sharing, leaked API keys/connection tokens, exposed PostgreSQL/S3, malicious uploaded documents, duplicate/incorrect ingestion, stolen device access, and accidental cloud costs. Treat personal-financial confidentiality and numeric correctness as security properties, not cosmetic preferences.

**Local MVP:** single user, backend binds to `127.0.0.1` by default, PostgreSQL not published to public network, private document folder excluded from version control/backups unless encrypted. If using Docker port mappings, bind published ports to loopback, not `0.0.0.0`. A truly remote network deployment **must have authentication** before exposure.

**No trading authority:** do not request or store brokerage trade credentials; allow only user uploads or explicitly authorized read-only provider APIs. A research agent can retrieve public data and summarize, never execute transactions.

## 2. Security baseline, every stage

- `.env` and all credentials ignored by Git; `.env.example` uses placeholder names only. Add a secret-scanning check and review staged diffs.
- Every document upload has a configured size cap, type validation by bytes/MIME, safe generated storage key, anti-path-traversal controls, and bounded parser time/memory. Avoid blindly processing arbitrary webpage URLs (SSRF).
- Set the application's local document directory permission to owner-only and do not serve it from Vite or an unauthenticated FastAPI route. A preview endpoint needs authorization and safe content disposition.
- Use parameterized queries/ORM; generated SQL cannot be supplied directly by external models. Enforce Pydantic validation and server-side permission/scope checks.
- Restrict worker-provider egress to approved services if feasible; disable remote AI unless specifically enabled. Never log statement text, API tokens, unmasked account identifiers, document images, or full raw remote prompts.
- Record provenance and immutable original files; edits to normalized data leave audit history and explanations. A parser bug must not erase the user's source of truth.
- Separate user-owned data from downloaded public financial data when choosing retention, backup, deletion and export policy.
- Pin dependencies and automate security update review for packages and container images.

## 3. Cloud inference and external accounts

The implemented AI setting is `PERSONAL_AI_ENABLED=false`. Startup rejects true: no live adapter or authorized service contract exists. `REMOTE_AI_ENABLED`, model-provider credentials and Ollama configuration are not finance runtime settings. No optional inference failure can enable a remote/paid fallback. Generic model routing and extraction/research/memory runtimes live in `personal-ai-system`; finance independently enforces what data may leave the app.

Before deployed real-data integration, require authenticated finance user identity, scoped service-to-service credentials with verified issuer/audience/expiry (or a reviewed equivalent), server-verified owner propagation and authorization at the upstream boundary. A fixed `local` owner or publicly reachable AI bootstrap is insufficient. Review upstream model data-use/retention, evidence/memory storage, logs, secrets, consent and minimized payloads. Finance owns private originals and canonical records; do not automatically add holdings/statements to shared memory. Keep the integration disabled until these checks have actual evidence. A trusted-local development mode may be designed later with explicit egress/storage rules; loopback configuration alone is not that review. See [ADR 0001](adr/0001-shared-personal-ai.md).

No real sensitive statements go to Gemini's unpaid API. Public research consent never authorizes private portfolio/account context. Tests must cover disabled, unauthorized, wrong-owner and malformed-result paths when a live adapter is added. Current tests cover the disabled boundary, candidate isolation and blocked enablement only.

If enabling Plaid later: use hosted consent/link flows, store only encrypted server-side access tokens, choose Investments/Transactions scopes intentionally, permit disconnect, and keep imports functioning without Plaid. Do not store online-banking passwords.

## 4. Local configuration and data portability

Illustrative future production settings (not all are implemented). Actual Stage 1 settings are in the root `.env.example`:

```dotenv
APP_ENV=development
DATABASE_BACKEND=postgres
DATABASE_URL=postgresql+psycopg://app:change-me@127.0.0.1:5432/portfolio
# Production: DATABASE_BACKEND=aurora_dsql; cluster endpoint/region/user via environment
# Production: use AWS compute IAM role, NOT a persisted database password
APP_BIND_HOST=127.0.0.1
FILE_STORAGE_BACKEND=local
PRIVATE_FILE_DIR=./.private/uploads
PRICE_PROVIDER=manual
ETF_PROVIDER_MODE=manual
PERSONAL_AI_ENABLED=false
# Account sync and paid-provider policy remain future gates, not live flags.
# No finance-owned model-provider URL or credentials.
```

Do **not** use the literal sample password outside an isolated local dev database. Production DSQL uses scoped IAM token-on-connect, not a static `DATABASE_URL` password. Validate environment combinations: production must fail startup if using dev secrets, open binding without auth, public bucket for private documents, or unsupported provider billing setting.

Finance can stay on AWS while personal-AI runs on another cloud. Future integration uses authenticated HTTPS with explicit egress/cost/retention controls; it requires no shared VPC, datastore or object bucket. This decision does not change PostgreSQL/DSQL, IAM/TLS, private S3 or AWS production gates.

Build portability around a shared logical schema, **distinct verified DSQL migration transactions** and `FileStore(local|s3)`/provider interfaces. App-managed CSV/JSON + original uploaded file export must restore on either backend; generic `pg_dump` is not assumed to work directly between environments. Support encrypted private export/import and **verify restore**. If exported archives contain real account data, encrypt them and warn about retention.

## 5. AWS reference deployment (Stage 4: Aurora DSQL required)

```text
Browser over HTTPS
  |-- CloudFront -> private S3 bucket for static Vite assets (OAC)
  `-- HTTPS FastAPI endpoint (small EC2 instance or reviewed Lambda deployment)
        |-- Same-codebase background jobs (local process or SQS-backed worker)
        |-- Aurora DSQL single-Region cluster via IAM tokens + TLS
        `-- Private S3 bucket for statements, screenshots, source archives
CloudWatch redacted metrics/logs; IAM role for compute; optional SSM config;
GitHub Actions + Terraform/CDK for approved deployments.
```

**DSQL is not a conventional RDS PostgreSQL instance.** It exposes service endpoints and enforces IAM + TLS connections. Use `sslmode=verify-full`, scoped `dsql:DbConnect` with a non-admin DB role, renewable authentication on new pool connections and tested reconnect logic. [AWS authentication](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/authentication-authorization.html) and [connection tokens](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_authentication-token.html). If private network connectivity is required, [Aurora DSQL PrivateLink](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/privatelink-managing-clusters.html) is an option with separate interface-endpoint costs; do not assume an RDS security-group/subnet design applies unchanged.

Infrastructure details:

1. Single AWS Region and one DSQL cluster. No multi-region replication initially. Ensure the chosen DSQL Region and compute Region are supported and close to each other; do not silently default to a costly region or multiple clusters.
2. Static site: private bucket + CloudFront. API: authenticated HTTPS on a small EC2 instance or a measured Lambda deployment. Verify total idle compute, networking, public IPv4/ALB, endpoints and logging costs. A DSQL cluster's idle DPU scaling does **not** remove EC2/ALB costs.
3. Files: **separate private S3 bucket** for statements and archive exports. Block public access; enable encryption, scoped IAM, sensible lifecycle, safe presigned URLs only through authenticated API, and verified recoverability.
4. IAM/TLS: production uses instance/task roles and scoped DB permissions; admin IAM role only for migrations. Never embed AWS access keys, statement contents or IAM tokens in Git, browser bundles or logs.
5. Backups: [AWS Backup supports DSQL](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/disaster-recovery-resiliency.html) but may be **billable**; choose a tested backup schedule plus separate encrypted, portable app exports (structured data + S3 originals) and rehearse importing back to local PostgreSQL.
6. No production deployment until the DSQL readiness suite in `07-aurora-dsql-compatibility.md` passes on a real cluster and importer retries/partial staging are verified.
7. Infrastructure-as-code should tag each resource and support teardown; make all optional chargeable services explicitly opt-in. Avoid NAT/PrivateLink/ALB solely because they appear in a generic AWS reference architecture.

**Database free allowance (AWS [official DSQL pricing](https://aws.amazon.com/rds/aurora/dsql/pricing/), checked 2026-09-25):** first **100,000 DPUs + 1 GB-month of Aurora DSQL storage per month** free, with **billable overages**. This differs from time-limited new AWS account promotional credits and must not be confused with permanent free RDS. AWS Compute, S3, CloudFront, data transfer, logging, AWS Backup, domain names and PrivateLink may still be charged. Free-tier benefits/eligibility and prices change; confirm in the actual account before deployment. **Budgets/alerts are warnings, not hard spend caps.**

## 6. Cloud launch gate

Before using real financial records remotely:

- [ ] Run full local PostgreSQL suite **and real Aurora DSQL compatibility suite**, including migrations, FKs/JSONB/NUMERIC, index readiness, token renewal/reconnect, bounded imports and OCC retries.
- [ ] Authenticate every API and document route; require HTTPS; use least-privilege IAM/DSQL DB roles and no embedded passwords or AWS keys.
- [ ] Test DNS/TLS verification and chosen DSQL connectivity path; PrivateLink is optional and must be budgeted if used.
- [ ] Validate private S3 policies and recoverability; no public statement access or leaked AI-provider data.
- [ ] Verify current 100,000 DPU / 1 GB-month DSQL allowance and **separately** estimate total monthly AWS cost after trial credits end; set budget alerts and inspect bills.
- [ ] Keep personal-AI disabled unless both services authenticate/authorize the user/service, owner propagation is verified, and consent, minimization, provider data-use/retention and redacted logging are reviewed. No silent paid fallback or sensitive unpaid-tier submissions.
- [ ] Test AWS Backup if enabled **and** export/restore of app records and raw files to local PostgreSQL.
- [ ] Test deterministic cleanup/teardown and verify billing/resource inventory, including backup vault, snapshots, IPs, CloudWatch log groups and S3 objects.
- [ ] Demonstrate a fully synthetic user journey in AWS before migrating private data.

## 7. Operational visibility and failure handling

- Track request/job IDs, provider failures, source-as-of age, import-review counts, unmatched holdings %, missing quote NAV %, daily provider calls and **DSQL DPU/storage usage**.
- Keep logs structured and redacted; never serialize statement text, account numbers or IAM connection tokens into errors.
- Offline mode/provider outage must not corrupt canonical holdings. On DSQL optimistic-concurrency failures, retry the bounded DB unit with idempotency; do not re-run paid API or LLM calls accidentally.
- If the DSQL free program changes or the full cloud topology exceeds budget, keep a documented **local PostgreSQL fallback and encrypted export path**. Returning to local is supported, but automatic two-way synchronization is explicitly not in scope.

## 8. Later scaling choices (not MVP requirements)

Consider ECS/Fargate or separated workers only when traffic or operational complexity warrants it. SQS is optional if the job interface cannot support a correct and cheap DSQL lease implementation; generic research search/indexing is owned by personal-AI and does not dictate finance DSQL capabilities. Maintain **production DSQL** as the SQL system of record unless the user explicitly changes this requirement.
