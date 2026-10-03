# Stage 4 implementation plan

**Status:** Implementation underway; no infrastructure provisioned or live DSQL verified
**Updated:** 2026-10-02
**Roadmap coverage:** Work packages 4.1–4.6

This is the execution plan for private AWS production hosting with **Aurora DSQL as the structured-data source of truth**. Read [security and deployment](06-security-and-deployment.md), [the DSQL contract](07-aurora-dsql-compatibility.md), and [the source/cost policy](03-data-sources.md) first. Stage 4 can be scheduled after [Stage 1](stage-1-implementation-plan.md); it does not require Stage 2, 3, or 5 features to be built first.

## Scope boundary

Stage 4 adds production configuration, personal authentication/authorization, IAM/TLS database access, private S3 storage, declarative single-region hosting, real DSQL release tests, whole-stack cost controls, encrypted portable export/restore, and gated deployment/rollback/teardown.

The smallest vertical slice is **authenticated HTTPS session → upload synthetic accepted CSV to private S3 → publish/query in real DSQL → inspect reconciled exposure → export and restore into isolated local PostgreSQL**. Modules are configuration, database/storage adapters, authorization, infrastructure, release checks and operator tooling. Domain calculations remain shared.

Production RDS PostgreSQL, automatic local/cloud synchronization, public finance hosting, multiuser SaaS, multi-region replicas, Kubernetes/Redis, speculative new product stages, and guaranteed free cloud hosting are excluded. Local PostgreSQL remains a complete independent personal deployment.

The [shared-AI ADR](adr/0001-shared-personal-ai.md) preserves this SQL/AWS topology. Personal-AI may run on another cloud; do not share databases/buckets or migrate finance hosting for that reason. Keep deployed real-data integration disabled until both sides enforce authenticated users/services, server-verified owner/scope propagation, least-privilege authorization, consent and reviewed provider storage/data-use/logging. Current finance and personal-AI local-owner seams do not satisfy this gate. Ordinary Stage 4 hosting does not require AI enablement.

## Delivery conventions and release gates

- Prepare reviewable infrastructure/configuration/cost plans before provisioning. Real deployment follows the roadmap's manual infrastructure, backup and budget approval gate; producing this document does not satisfy it.
- Separate local/test/production settings. Production fails closed on missing authentication, unsupported database backend, public private-data storage, dev secrets or unreviewed billable provider fallback.
- Use official DSQL dialect/connector and IAM token-on-connect with verified TLS; application role is non-admin, migration identity separately scoped.
- Version DSQL migrations with one DDL statement per transaction, no mixed DDL/DML, resumable ledger checkpoints, and asynchronous index readiness before dependent steps.
- Authenticate app pages/API and authorize every data, preview, upload, export, job and admin path. A static frontend bucket can remain private behind CloudFront; serving its bundle alone is not an authenticated financial-data boundary.
- Bind records/jobs to a verified principal/scope; client-supplied owner identifiers never grant access. Keep personal deployment simple, without implementing household roles.
- Raw statements/originals belong in a separate private S3 bucket, not the frontend bucket or large DSQL JSON fields.
- Reverify current AWS features/regions/prices/allowances and provider terms before selecting resources. The source docs' dated allowance is background, not a fresh pricing verification.
- Forecast compute, database overages, storage, transfer, logs, backup, domain, and optional queue/endpoints separately. AWS budgets notify; application limits and teardown reduce exposure but do not guarantee an account-wide hard spending cap.
- Routine PR CI stays local/offline. Every enabled persistent/job/research feature additionally needs real DSQL evidence before production promotion.

## Required verification matrix

| Gate | Required evidence |
| --- | --- |
| Configuration | Valid local/prod settings, denied auth bypass/static tokens/public storage/wrong backend |
| Authentication | Signature/issuer/audience/expiry or selected session equivalent; login/logout/revocation; unauthenticated/cross-scope denial |
| Database | Fresh/upgrade full deployed schema, UUID/NUMERIC/JSONB, FK/uniqueness, async indexes/ledger recovery on real DSQL |
| Connection lifecycle | IAM/TLS verification, new connection after token expiry, pooled reconnect/connection lifetime handling |
| Import/exposure | Same snapshot twice, 500-row staged fund import, concurrent publish, injected real OCC conflict, safe-batch failure, golden NAV/residual |
| Storage | Public access blocked, scoped read/write, unsafe keys rejected, authenticated expiring preview, originals intact |
| Jobs if enabled | Real chosen SQS/DSQL lease retry, duplicate delivery, expiry/fencing, cancel, no duplicated outputs/calls |
| Cost/security | IaC resource/IAM inventory, dated whole-stack forecast, redacted logs, alerts/kill switches, no secret in bundles |
| Recovery | Encrypted structured-plus-original export, hash/count/lineage validation, isolated PG restore; budgeted AWS backup drill if selected |
| Release/operations | Synthetic HTTPS journey, migration/resume, rollback, pause, teardown/resource inventory and billing follow-up |

Skipped real-cluster tests are **unverified**, not successful. The applicable suite covers the actually deployed stage/schema, not just the original Stage 0 spike.

## Required implementation artifacts

**Required control records:**

| Record | Required fields / use |
| --- | --- |
| Principal mapping | Stable subject/issuer, authorized personal scope, status, created time; explicit local-data import mapping |
| Security audit | Actor/scope, action, target ID/type, result, correlation ID, time; no document/account content |
| Migration/release evidence | Build/schema/config/fixture versions, backend/test environment, gate results, approval, execution date, rollback compatibility |
| Export manifest | Format/schema version, record/file counts, object/content hashes, source relationships, currency/decimal representation, encryption metadata without keys |
| Resource/cost register | Account/region, resource/tag, purpose, permissions, current unit prices/check date, expected idle/usage cost, retention/teardown owner |

**Required configuration and operations:**

| Boundary | Requirement |
| --- | --- |
| `APP_ENV`, `DATABASE_BACKEND` | Explicit production + `aurora_dsql`; local remains `postgres` |
| DSQL settings | Supported region/endpoint/non-admin user, IAM role credentials, TLS verification, bounded pools/transactions/retries |
| FileStore | Local or S3; private statement bucket distinct from static assets; encryption and safe access policy |
| Auth | Selected provider/session, allowed personal subject(s), issuer/audience/origins, no production bypass |
| Optional personal-AI | Default off; agreed bounded HTTPS contract, verified user/service/owner authorization and reviewed data handling before private data |
| Cost/provider gates | Paid fallback off; per-provider work limits, worker pause and refresh kill switches; alert policies |
| Operations | Explicit environment/apply target; separate migrate/release/rollback/export/restore/teardown commands |

Existing portfolio APIs keep their OpenAPI schemas while adding consistent 401/403/scope errors. Add export/status or operator contracts only as needed; never expose raw IAM/database tokens to the SPA. Generate client changes from OpenAPI.

## Dependency map

```text
Stage 1 + S0.4 ─> S4.1.1 Production config/storage ─┬─> S4.1.2 Auth/security
                                                   └─> S4.3 Full real-DSQL suite
S4.1.1 + S4.1.2 ─> S4.2 IaC/runtime selection ─> S4.4 Cost/approval
S4.1.1 + S4.1.2 + test environment ─> S4.5 Recovery drill
S4.2 + S4.3 + S4.4 + S4.5 ─> S4.6.1 Gated release ─> S4.6.2 Synthetic operations/teardown
```

Configuration/IaC/tests/runbooks can be prepared locally. Credentialed cluster execution and resource application require the documented AWS target and approval; personal data stays local until all launch gates pass.

---

## Stage 4 — AWS production deployment track

### S4.1.1 — Implement production configuration and storage adapters

**Dependencies:** Stage 1; Stage 0 DSQL boundary implementation.  
**Modules:** settings, database engine/migration runner, FileStore.

**Goal:** switch infrastructure without duplicating portfolio business logic.

**Work:**

1. Validate production backend, region, IAM/TLS, pool/retry/batch limits, storage selection, auth-required policy, origins, and disabled paid fallback at startup.
2. Reverify and pin the official DSQL dialect/connector; exercise token-on-new-connection and pool recycling under actual documented connection behavior.
3. Implement private S3 FileStore with generated keys, hashes, encryption, access scope, bounded transfer, retention metadata and authenticated short-lived preview/download support.
4. Complete the deployable schema's DSQL migration sequence/ledger, index waiting and failed-step resumption; keep data backfills as bounded DML separately.
5. Keep local settings and original-file storage usable independently; no automatic copying/synchronization.

**Requirements:** application compute gets scoped role credentials, never persisted DB passwords/access keys; no cloud/private storage defaults that leak data. Files remain source-linked when moving via explicit export/import.

**Acceptance criteria:** config tests fail unsafe combinations; both FileStores satisfy the same contract; S3 policy denies anonymous reads; real DSQL reconnect/migration behavior is verified or marked pending; no domain service branches on cloud engine for financial formulas.

**Out of scope:** production traffic, automatic data migration, RDS, and network topology copied from conventional PostgreSQL hosting.

### S4.1.2 — Add personal authentication and end-to-end authorization

**Dependencies:** S4.1.1.  
**Modules:** auth/principal dependencies, repositories, web access, jobs/storage/export policy.  
**Decision required:** acceptable personal identity/session provider and recovery procedure.

**Goal:** prevent public access to financial routes and originals.

**Work:** choose and document a minimal personal authentication model; implement verified login/session/token validation, subject allowlist/mapping, expiry/logout/revocation and recovery; inventory routes/files/admin/jobs and enforce scope on lookups/writes; gate application navigation/data behind authentication; add secure CORS/session/CSRF controls appropriate to the choice; map deliberately imported local data to the approved scope.

**Requirements:** auth is enforced by the backend and storage policy, not only the UI. Jobs run under explicit application authority with scoped record access. Any public health probe is minimal and returns no financial/configuration information. Do not trust client owner IDs.

**Acceptance criteria:** no/invalid/expired/wrong-audience credentials and wrong subject cannot read/import/export/preview or administer data; spoofed IDs fail scope checks; logout/revocation and local development modes behave deliberately; logs/errors are redacted; scope migration is dry-run capable and idempotent.

**Out of scope:** multiuser household roles, subscriptions, public sharing, and assuming IAM DB login authenticates the app user.

### S4.2 — Prepare declarative single-region infrastructure

**Dependencies:** S4.1.1, S4.1.2.  
**Modules:** `infra`, build/deploy packaging, operator docs.  
**Decision required:** AWS account/region, Terraform versus CDK, measured API runtime/connectivity.

**Goal:** define the smallest secure topology with a reviewable resource inventory.

**Work:**

1. Compare small EC2 and measured Lambda compatibility for API/worker runtime, pooling, document processing, cold starts, networking and total cost; select one, document the alternative's tradeoff.
2. Define one supported single-region DSQL cluster, private statement/export bucket, private static bucket with CloudFront OAC, authenticated HTTPS API and scoped compute/migration IAM.
3. Add queue/worker resources only for implemented Stage 2 jobs; select tested DSQL lease or explicitly budgeted SQS behind the existing interface.
4. Tag resources, bound logs/retention, declare secrets/config bindings, lock IaC/provider versions, and produce a plan/diff without applying it.
5. Document DNS/TLS, connectivity and teardown. Optional PrivateLink/NAT/ALB/endpoints must have a named requirement and cost line; DSQL is not described as RDS in a subnet.

**Requirements:** no embedded secrets/admin privileges in app roles; no multi-region duplication; private files separate from frontend assets; production infrastructure application has an explicit target and approval gate.

**Acceptance criteria:** IaC checks/plan show exactly the chosen resources/roles/buckets/network paths; public-statement and broad-IAM assertions fail tests; runtime smoke/benchmarks support the choice; resource outputs/commands are sanitized and reviewable before provisioning.

**Out of scope:** applying unapproved resources, microservice migration, generic enterprise cloud topology, and speculative worker/search infrastructure.

### S4.3 — Execute the full real-DSQL release suite

**Dependencies:** S4.1.1; approved test cluster/access; all deployed feature schemas.  
**Modules:** gated database/integration suite, evidence reports.

**Goal:** establish production compatibility on the actual required database.

**Work:** run fresh-install and previous-version upgrade with FK/uniqueness/index readiness and ledger interruption/resume; UUID/NUMERIC/JSONB round-trips; IAM/TLS/token-expiry/new-pool-connect tests; identical snapshot import and 500-row fund import/publication; configured batch-limit failure; concurrent publish and intentionally conflicting real transactions with bounded retry; golden exposure/residual; enabled job/tax/history/research repository cases for the actual release.

**Requirements:** fixtures are synthetic and capped; conflict tests demonstrate real DSQL behavior rather than only monkeypatching an exception. External-call counters prove OCC retries do not re-fetch/re-infer. Clean test data/resources under a documented scoped procedure.

**Acceptance criteria:** every applicable DSQL matrix row has a result tied to code/schema/dialect/fixture version and execution date; migration/index errors block promotion; retries/exhaustion retain one visible publication or none; no credentials in evidence; PG-only or skipped checks cannot satisfy the gate.

**Out of scope:** assuming the Stage 0 smoke covers later schema changes, and performance/load tests that threaten the approved spend envelope.

### S4.4 — Verify whole-stack costs and enforce practical limits

**Dependencies:** S4.2 resource plan; current official pricing/account verification.  
**Modules:** cost register, provider/worker controls, observability/IaC alerts.  
**Decision required:** approved monthly exposure, alert recipients/thresholds and optional billable services.

**Goal:** make idle and active costs visible before launch.

**Work:** record dated DSQL allowance/account eligibility and excess rates; forecast low/expected/high usage for compute, DSQL DPU/storage, S3 requests/storage, CloudFront/transfer, logs, backups, domain/IPs and optional SQS/PrivateLink/network services; set AWS budget/usage alerts; cap app refresh/work/concurrency/retention and disable unknown/paid fallback; add worker/provider pause/kill-switch procedures and a billing review schedule.

**Requirements:** promotional credits and recurring allowances are separate lines; never equate database allowance with free hosting or alerts with hard caps. Estimate costs after credits expire and identify which usage cannot be capped by the app.

**Acceptance criteria:** a dated forecast covers every resource in IaC; synthetic limits block excess provider/job work safely; alert routing is tested where feasible; operator can stop schedules/provider calls without corrupting data; infrastructure/budget approval is recorded before apply.

**Out of scope:** permanent free-hosting claims, automatic paid upgrades, and relying solely on AWS budget email to prevent spending.

### S4.5 — Implement security, encrypted export and tested recovery

**Dependencies:** S4.1.1, S4.1.2; approved synthetic cloud test environment.  
**Modules:** export/import tool, FileStore, backup configuration, security/runbooks.

**Goal:** recover personal data and return to local operation deliberately.

**Work:**

1. Audit IAM non-admin access, TLS host verification, bucket policies, upload/preview controls, dependency/secrets exposure and redacted logs.
2. Define a versioned portable archive of structured records plus originals, decimal/currency/timestamp conventions, hashes, lineage and reference counts; encrypt private exports and handle keys outside the archive/logs.
3. Obtain a consistent export using frozen published revision IDs and a manifest; document snapshot/maintenance-window policy for mutable records so exports do not mix revisions.
4. Import into isolated PostgreSQL through validated bounded staging with explicit scope/ID mapping and idempotency; verify counts, hashes, dates, original evidence and financial reconciliation.
5. If AWS Backup is selected/budgeted, verify current support/permissions/retention and rehearse restore; document recovery objectives, operator steps and source/backup deletion limitations.

**Requirements:** native `pg_dump` is not assumed portable to/from DSQL. Encrypted exports are access-controlled with explicit retention. A drill must not overwrite the user's local database or imply automatic sync. Restore errors leave target publication incomplete/unselected.

**Acceptance criteria:** synthetic DSQL→archive→isolated PG restore reproduces golden NAV/exposure and source links/original hashes; missing/tampered files, incompatible schemas, wrong keys and interrupted/repeated imports fail or resume safely; credentials/private data stay out of reports; selected backup method is actually rehearsed before real cloud data.

**Out of scope:** untested backups described as recovery, automatic local/cloud reconciliation, and undocumented deletion from immutable backups.

### S4.6.1 — Build gated CI/CD and safe rollback

**Dependencies:** S4.2–S4.5; S4.1.2 security gate.  
**Modules:** GitHub Actions, release manifests, deploy/migrate/rollback runbooks.

**Goal:** promote only tested immutable builds with explicit operator approval.

**Work:** preserve offline PR quality tests; add gated credentialed DSQL workflow/manual equivalent with narrowly scoped temporary credentials; link release evidence to build/schema/config versions; stage migrations before traffic; require applicable real-DSQL/security/recovery/budget gates and manual production approval; deploy immutable artifacts; document schema-compatible app rollback and failed migration resumption.

**Requirements:** a skip cannot become a green production gate. DSQL schema changes may not be transactionally reversible as a unit; rollback must distinguish traffic/build rollback from forward schema repair and data recovery. Secrets never enter workflow output/client artifacts.

**Acceptance criteria:** failed or missing gate blocks promotion; dry-run/approved synthetic deployment selects the explicit environment; failed migration leaves a resumable ledger and no traffic on incompatible code; rollback restores a compatible version without discarding financial data; actual commands/prerequisites are documented.

**Out of scope:** unattended infrastructure approval, destructive down-migrations as a generic rollback, and always-on expensive cloud CI.

### S4.6.2 — Rehearse the synthetic launch, operations and teardown

**Dependencies:** S4.6.1; approved synthetic deployment.  
**Modules:** launch checklist, monitoring, incident/teardown runbook.

**Goal:** verify private production use and a controlled exit before moving real records.

**Work:** perform authenticated HTTPS create/import/exposure journey with private S3 and real DSQL; demonstrate duplicate/retry/OCC behavior; trigger provider failure and worker pause where implemented; complete export/restore; exercise compatible app rollback; inventory/tag resources and rehearse controlled shutdown/teardown with data-retention safeguards; verify remaining buckets/backups/log groups/addresses/endpoints and follow up on charges.

**Requirements:** distinguish stopping compute from deleting retained data/DSQL/backups. Real-data deletion requires explicit intent; a synthetic rehearsal uses isolated labelled resources. Monitoring uses IDs/counts/durations/ages/DPU/storage, never statements/tokens.

**Acceptance criteria:** launch checklist records auth/storage/DSQL/correctness/recovery/cost results; no public raw statement or financial route; operator can pause/recover/return local; teardown inventory identifies any intentionally retained billable resources; production access is approved only after all gates pass.

**Out of scope:** silently uploading real financial records, claiming immediate final billing visibility, and broad account cleanup outside the app resource inventory.

## Stage 4 completion review

1. Does the authenticated HTTPS app use real Aurora DSQL with non-admin IAM and verified TLS?
2. Are every financial/document/job/export route and underlying storage operation authorized?
3. Does the actual deployed schema/feature set pass real migrations, index, import, OCC and Decimal tests?
4. Are raw files private and logs/secrets/provider policies reviewed?
5. Can a consistent encrypted export restore into independent local PostgreSQL with matching originals/totals?
6. Are whole-stack costs after credits, usage controls and alert limitations understood and approved?
7. Can an operator pause, resume migrations, roll back the app and tear down scoped resources safely?

Only after all answers are yes and the manual launch gate is satisfied should private financial data be imported to production.

**Release handoff:** publish actual infrastructure/migration/release/rollback/export/restore/teardown commands, chosen identities and runtime, dated cost/provider checks, schema-bound DSQL evidence, recovery drill, retained-resource inventory, and incident/usage review procedures.
