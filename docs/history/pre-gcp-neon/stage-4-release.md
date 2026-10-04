> Historical snapshot at `4e5f3e3`, preserved 2026-10-03. Deployment guidance is superseded by [ADR 0002](../../adr/0002-gcp-neon.md). Do not use this snapshot as current instructions.

# Stage 4 release evidence

**Status:** S4.1–S4.6 production configuration, infrastructure, real-DSQL evidence machinery, cost controls, encrypted portable recovery, and fail-closed release/operations tooling prepared locally; no AWS resources provisioned and live DSQL/cloud launch remain unverified
**Updated:** 2026-10-03

This record distinguishes locally implemented release machinery from credentialed launch evidence. A passed SQLite/PostgreSQL test or skipped AWS suite does not satisfy the real Aurora DSQL, bucket-policy, cost-approval, recovery, or HTTPS launch gates.

## 2026-10-03 review update

The [repository review](maintainability-review.md) verifies local recovery in the ordinary quality gate and moves infrastructure tests to `tests/infra`. Release hashes now cover fixtures, infrastructure tests and missing build/migration inputs; changes require new evidence. Authentication database failures return safe request-correlated 503s, callback session writes leave the async loop, and the container uses redacted route-template logs rather than logging callback queries. S3 duplicate reuse verifies object bytes and streaming cleanup handles malformed metadata. The current schema has 18 Alembic revisions and 95 DSQL migration steps; earlier step counts below describe their original stage. No real DSQL, S3, cloud runtime or AWS recovery gate was cleared.

## S4.1 — Production configuration, storage and authentication

The API now accepts explicit `development`, `test`, and `production` settings. Production startup fails closed unless it has HTTPS origin, the single-person authentication configuration, Aurora DSQL, a separate migration role, private S3 storage, and secure cookies. Production's effective worker default is `false`; the same parsed value is checked and returned, and explicit `true` or malformed values fail startup. Import file limits cannot exceed the private-object limit. Local PostgreSQL and filesystem storage remain defaults for offline operation.

All private file consumers now share the `FileStore` interface. The local store enforces configured read/write bounds, owner-only permissions, generated content-addressed keys, regular-file checks, and SHA-256 verification; corrupt oversized existing objects fail before hashing. The S3 adapter uses a generated SHA-256 key, conditional create, explicit server-side encryption, bounded reads/writes, and hash/size verification, and closes streaming bodies even when reads fail. It does not return S3 URLs; authenticated API routes stream file content through the backend. IAM policy, S3 public-access controls, encryption-key policy, region availability, and actual transfer behavior are not yet verified in AWS.

Authentication uses a provider-neutral OpenID Connect authorization-code flow with PKCE `S256`. Authlib verifies callback state, code challenge, ID-token signature against discovered JWKS, issuer, audience, expiry, and nonce; the app then requires the configured exact `(issuer, subject)` and server-owned personal scope. OIDC uses a short-lived signed `HttpOnly`, `Secure`, `SameSite=Lax` transaction cookie for the cross-site callback. A verified login creates a separate opaque `HttpOnly`, `SameSite=Strict` session cookie; only its SHA-256 digest is stored. The server checks active subject, issuer, scope, revocation, and expiry on every `/v1` request, offloading synchronous SQL lookups to Starlette's thread pool so the async loop remains responsive. Session create/revoke operations use bounded database-only OCC retries with stable IDs; provider verification and token exchange stay outside retry callbacks. Mutations require the configured `Origin` and reject cross-site fetches. Logout revokes the database session. Redacted login/logout audit rows carry the server-generated request correlation ID. The SPA waits for session validation, gates all finance workspaces behind sign-in, clears React Query data on 401/logout, and provides sign-out. `/health` and `/health/ready` expose only status. The OIDC provider/client, callback registration, and stable subject are operator settings; no live provider is configured or exercised.

Generate `AUTH_SESSION_SIGNING_KEY` with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`; inject it and `AUTH_CLIENT_SECRET` through a secret store. Register the exact callback `https://<APP_PUBLIC_ORIGIN>/api/v1/auth/callback`; the planned CloudFront API behavior strips `/api` before FastAPI receives the request. `uv run --directory services/api --locked python -m app.auth.bind_principal` reports table counts and whether the configured `(issuer, subject, scope)` is already bound without writing; `--apply` creates the one mapping and refuses to replace a different one. Neither command transfers local records to cloud. Any eventual initial data move uses the separate reviewed export/import workflow.

PostgreSQL Alembic revision `0015_stage4_authentication` adds three auth/audit tables and two indexes; no applied migration was changed. The DSQL plan has matching independent table/index steps and resumable ledger checks. The whole plan currently contains 83 steps (38 table, 32 async-index, 6 alter, 3 add-constraint, 2 drop-constraint, 1 async-alter, and 1 bounded backfill). The plan checks are structural only; no live DSQL migration was run.

Offline validation for this package:

```sh
services/api/.venv/bin/pytest -q \
  services/api/tests/test_auth.py \
  services/api/tests/test_file_store.py \
  services/api/tests/test_config.py \
  services/api/tests/test_database_engine.py \
  services/api/tests/test_dsql_migrations.py
services/api/.venv/bin/ruff check services/api/app/auth \
  services/api/app/config.py services/api/app/db/models.py \
  services/api/app/db/dsql_migrations.py services/api/app/main.py \
  services/api/app/storage services/api/tests/test_auth.py \
  services/api/tests/test_file_store.py services/api/tests/test_config.py \
  services/api/tests/test_database_engine.py \
  services/api/tests/test_dsql_migrations.py
pnpm --filter web typecheck
```

The synthetic auth tests cover RSA-signed ID-token acceptance, invalid-signature and wrong-subject rejection, issuer/audience/expiry checks, client-claim scope rejection, secure cookie attributes, CSRF denial, owner-only access, logout revocation, and issuer/subject principal-map idempotency. Synthetic FileStore tests cover conditional S3 create, SSE selection, content hash, key validation, and size limits. Database/migration tests compile through the official DSQL dialect and check resumable migration structure. None of these tests use an AWS credential, S3 bucket, DSQL cluster, or configured identity provider.

## Remaining launch gates

| Package | Prepared or delivered locally | Evidence still required |
| --- | --- | --- |
| S4.1 | Production configuration, auth, private storage adapter, and `0015` migration plan | Real DSQL migration/reconnect, scoped IAM and S3 policies, HTTPS synthetic journey |
| S4.2 | Terraform lockfile, provider schema validation, static policy guardrails, and fake-input no-network plans prepared; App Runner deployment has a default-false existing-customer eligibility guard | Explicit account/region/domain/certificate/image/identity/budget inputs; confirm target-account App Runner eligibility or approve a replacement runtime; target-specific reviewed plan, runtime smoke/benchmark, and approved apply |
| S4.3 | Thirteen required real-DSQL cases and fail-closed evidence runner prepared, including populated prior-schema upgrade, interruption/resume, configured batch-limit rejection, and a 16-minute IAM token-expiry reconnect case | Execute against a fresh approved isolated DSQL cluster with `RUN_DSQL_TOKEN_EXPIRY_TEST=1` and pass with zero skipped tests; the token-expiry case takes at least 16 minutes |
| S4.4 | Bounded production workload settings, optional post-credit account budget alerts, and dated public-price register prepared on 2026-10-03; fake-input disabled/enabled plans succeeded and missing-recipient plan failed closed | Target account/Region and credit eligibility, region-specific whole-stack forecast, selected monthly threshold, verified recipients, and alert delivery test |
| S4.5 | Versioned AES-GCM portable archive, scope-confirmed CLI, isolated loopback PostgreSQL restore, and synthetic interruption/tamper/idempotency drill | Approved isolated DSQL + private S3 export/restore drill, security/IAM/bucket audit, and explicit retention/RTO/RPO/budget approval |
| S4.6 | Offline evidence-bound gate and release/operations runbook prepared; unit tests cover missing, stale, skipped, mismatched, and tampered evidence | All target-bound evidence, real DSQL/HTTPS/S3/recovery operations rehearsal, and separate production approval; App Runner eligibility or reviewed replacement runtime remains unresolved |

The current published DSQL free tier is 100,000 DPUs plus 1 GB-month of storage per month, with billable overages; it is not a whole-stack cap. AWS account, target region, identity, alert recipient, monthly exposure, and deployment approval have not been supplied. No infrastructure apply, cloud test, data transfer, push, or deployment is authorized by this release record.

## S4.2 — Declarative single-region infrastructure preparation

[`infra/terraform`](../infra/terraform/README.md) selects one DSQL cluster,
private statement/export S3, separate private static S3 behind CloudFront OAC,
an immutable ECR image, App Runner, and scoped runtime and operator migration
roles. The API/edge resources default off. A first reviewed foundation apply
would create the ECR repository before an operator builds and pushes an image;
the second reviewed plan would use its immutable digest and enable App Runner
and CloudFront. No stage has been applied here.

The prepared choice is App Runner for the existing containerized ASGI API,
default public egress to DSQL, and no separate VPC/NAT/ALB/PrivateLink. It is a
documented fit, not a measured result: one 0.25-vCPU/1-GB instance, concurrency
10, and max/min 1 are provisional bounded settings, with smoke/benchmark and
account pricing review still required. Lambda's adapter/cold-start/pool and
document-processing tradeoffs and EC2's host patching/idle-cost tradeoff are
recorded in the IaC README. App Runner's direct service URL is public and
bypasses CloudFront; the API's backend auth is required at either origin. No
WAF, VPC/NAT, PrivateLink, SQS, customer KMS, or automatic worker is introduced.

The infrastructure resources carry environment, app, owner, stage, data-class,
and purpose tags where the AWS service supports resource tags. S3 has public
access blocked and TLS-only policies; private objects are never a CloudFront
origin. The static origin is readable only by the exact distribution OAC. App
Runner runtime access is limited to the DSQL `DbConnect` action on this one
cluster, private bucket file reads/writes, and the two configured auth secret
ARNs; its separate migration role trusts one explicit IAM principal and alone
has DSQL `DbConnectAdmin`. ECR's required `GetAuthorizationToken` is the only
wildcard resource permission. App Runner auto-deploy is off and the image must
be selected by digest. Stage 2 jobs remain disabled.

CloudFront uses the AWS managed `AllViewerExceptHostHeader` origin request
policy, forwarding cookies, OIDC callback query strings, every declared and
manually read API header, and future client contract headers while preserving
the origin `Host`; the API cache policy has zero TTL. A viewer-request
function removes the public `/api` prefix before FastAPI; a separate static-only
function handles SPA routes, so API error statuses remain intact. DNS, the
validated `us-east-1` ACM certificate, identity-provider registration, secrets,
Terraform remote state backend, resource owner, AWS account/region, exact
subject/scope, and monthly budget remain operator inputs.

AWS App Runner creates log groups with generated service IDs and they default to
indefinite CloudWatch retention. The checked helper sets and verifies 30 days;
doing so after creation/replacement is a mandatory launch gate. Terraform
`1.16.5` `fmt` and `validate` passed after the CloudFront header-forwarding edit. `.terraform.lock.hcl` records HashiCorp
AWS provider `6.67.0` and Random provider `3.7.2` checksums fetched from their
official registry. Fake-input no-refresh plans described 18 foundation
resources and 30 total resources when App Runner/CloudFront were enabled with
the optional budget off; a separate plan with the budget enabled described 19
foundation resources, and a plan with a configured budget but no recipient
failed closed. They used temporary local skip-STS settings, fake credentials,
and a closed localhost proxy, and were saved outside the repository. They do not prove
the actual account's resource availability, quota, costs, identity, or DNS/TLS.
No account API was queried, no App Runner runtime was benchmarked, and there has
been no real target plan, Terraform apply, image build/push, DNS/TLS test, DSQL
connection, or AWS resource call.
Local guardrails are executable with:

```sh
python3 tests/infra/test_infra_contract.py
bash -n scripts/stage4/set-apprunner-log-retention.sh
```

## S4.3 — Real Aurora DSQL suite and evidence gate

The gated suite requires thirteen named cases. It covers the complete versioned
migration plan and representative synthetic schema/UUID/`NUMERIC`/JSONB round
trips, current tax/event/auth tables, auth/session constraints, fresh app-role
IAM/TLS reconnect, a real competing-write retry, snapshot replacement/history,
the configured over-limit fund import failure, hidden interrupted staging,
concurrent publication, and golden report values. Additional cases upgrade a
populated core-only schema, resume after DDL commits before its ledger update,
and wait 16 minutes before reconnecting with a newly generated IAM token.
The application role and migration role are supplied separately. The new auth
checks exercise the deployed migration-0015 tables using only synthetic IDs.
Every feature case has scoped cleanup and does not target local or user data.

`app.release.dsql_evidence` is the promotion runner. It requires the exact
`RUN_DSQL_INTEGRATION=1`, `DSQL_TEST_CLUSTER=disposable`,
`RUN_DSQL_TOKEN_EXPIRY_TEST=1`,
`DATABASE_BACKEND=aurora_dsql` opt-in, a DSQL endpoint, AWS region, and distinct
non-admin application/migration roles. It captures pytest/JUnit only in a
temporary directory, never prints or saves raw output, and emits a mode-0600
summary bound to source commit, application build, Alembic/DSQL schema plan,
sanitized configuration, fixture, immutable OCI image digest, and hashed cluster
identity. The `check` command requires the same runtime configuration and image
digest to still be selected. Missing required cases, a nonzero test result, or
any skip writes failed/blocked evidence; `check` rejects skips, failures,
incomplete suites and stale fingerprints. The prior-schema case starts from the
core-only schema and preserves a populated synthetic issuer while applying the
remaining plan; it requires a fresh isolated DSQL cluster. The interruption
case commits DDL, injects failure before its ledger write, then resumes and
checks the object. The configured batch-limit case submits one row beyond the
runtime limit and confirms rejection before persistence. The IAM-expiry test
waits 16 minutes and reconnects with a newly generated token; offline runs skip
it, which keeps promotion blocked until the operator explicitly enables it.

Run only after supplying credentials to an explicitly approved isolated,
disposable test cluster and confirming its spend envelope:

```sh
export RUN_DSQL_INTEGRATION=1
export DSQL_TEST_CLUSTER=disposable
export RUN_DSQL_TOKEN_EXPIRY_TEST=1
export DATABASE_BACKEND=aurora_dsql
# Also set AWS_REGION, the DSQL endpoint and distinct scoped roles, and
# RELEASE_IMAGE_DIGEST to the reviewed source-matched sha256 OCI image digest.
uv run --directory services/api --locked python -m app.release.dsql_evidence \
  run --evidence /secure/operator/path/dsql-evidence.json
uv run --directory services/api --locked python -m app.release.dsql_evidence \
  check /secure/operator/path/dsql-evidence.json
```

The test harness can verify a newly opened IAM/TLS connection after disposing
the old pool. Its new expiry case waits 16 minutes before reconnecting with a
new token and remains explicitly opt-in. The populated-core-schema upgrade,
DDL interruption/resume, and configured row-limit rejection cases are now
executable on the isolated disposable cluster; the OCC case coordinates
competing transactions and passes only if DSQL itself reports the retryable
conflict. No DSQL cluster was configured here: a direct default invocation
reported all thirteen gated cases skipped, and no evidence record was issued.
Local evidence-gate tests prove that skip/failure/stale-schema records cannot
be promoted. Live DSQL therefore remains **unverified**.

## S4.4 — Cost controls and register

[`stage-4-cost-register.md`](stage-4-cost-register.md) records official AWS
pricing pages checked on 2026-10-03, resource-specific usage drivers, App Runner
and DSQL examples, workload assumptions, and the account-specific inputs still
needed for an actual forecast. App Runner's provisional ceiling is one
0.25-vCPU/1-GB instance with concurrency 10; the API receives 1,000-row import,
5-MB import file, 20-MB private-file, 40-page PDF, 8-second parser, and three
job-attempt limits. The 1,000-row default is constrained to 502–1,000 to
preserve the largest current synthetic release fixture. Job workers and
personal-AI remain disabled.

Terraform adds a disabled-by-default, whole-account monthly USD AWS Budget in
the billing control plane's `us-east-1` Region. When explicitly configured, it
alerts at 50% actual, 80% forecast, and 100% actual; it excludes credits to flag
the post-credit charge profile and creates no budget actions. At least one
valid recipient (up to ten) is required. AWS announced email verification for
newly added recipients effective 2026-09-30; the recipient must confirm through
the target account before mail is delivered. AWS Budgets data is delayed, so
notifications are not an account cap or emergency shutdown.

S3 original and export retention remains indefinite until an explicit user-data
retention policy and recovery plan are approved; no expiry rule silently
deletes user records. ECR retains 20 immutable API images. App Runner generated
logs have a 30-day post-create retention helper gate. Per-request bounds, one
running instance, and disabled optional features reduce exposure but cannot cap
aggregate DSQL, S3, CloudFront, egress, or log spend. No budget amount, alert
recipient, account query, real pricing-calculator estimate, or alert-delivery
test was possible.
Full budget/target forecast evidence remains launch-gated.

The 30 configuration tests pass, including the injected 1,000-row/file/page/
parser/job limits and over-bound configuration rejection. Five Terraform
contract tests pass, including the App Runner eligibility precondition.
Terraform 1.16.5 formatting, schema validation, and fake-input no-refresh plans
passed before that precondition was added. No Terraform executable is available
for a fresh format/validate/plan run after the edit.
The fake `.invalid` recipient was used only to validate a no-refresh local plan;
it is not an alert routing or recipient confirmation test.

AWS's current [App Runner availability notice](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html), checked 2026-10-03, says AWS stopped accepting new customers on 2026-03-31 while existing customers may continue. The target account's eligibility is unknown. Terraform now refuses to create its API service unless an operator explicitly confirms existing-customer eligibility. A new or ineligible account needs a separately reviewed runtime decision and updated whole-stack cost forecast; none has been selected here.

## S4.5 — Encrypted portable export and validated local recovery

`app.recovery.cli` exports the current finance schema, immutable originals, and
frozen report artifacts into a versioned `.pfarc` archive. It uses chunked
AES-256-GCM with a per-archive random salt/nonce prefix and Scrypt; the
passphrase is prompted interactively and is not written to the archive or
reports. The encrypted manifest records schema identity, source snapshot time,
Decimal/string and time encodings, counts, row/object hashes, and finance
lineage. Source records are read in one read-only Repeatable Read transaction;
objects are size/hash checked. Archive, record, table, row-count, and object
sizes are bounded. The archive omits sessions, principal mappings, security
audit identities, and leased jobs so authentication and runtime authority are
deliberately rebound at the destination.

Restore requires a migrated, empty, specifically prefixed loopback PostgreSQL
database, a distinct private directory named for that database, explicit
source/target scope mapping, and a matching acknowledgement. It commits bounded
200-row batches inside an archive-specific PostgreSQL staging schema, keeps
selected account snapshot pointers unpublished until all related rows are
restored, verifies staged hashes and counts, then atomically publishes the
schema while retaining the old empty schema for inspection. A private restore
marker supports safe retry. It refuses remote, nonempty, app, mismatched-schema, and
application-file-directory targets. It never creates a database, deletes user
data, switches app configuration, or uploads data to cloud.

Synthetic PostgreSQL verification uses a temporary `pf_source_*` database and
a separate `pf_restore_*` database. It covers correct-key round trip, wrong
key, archive tampering, missing/tampered objects, incompatible schema,
interruption after a committed database batch, successful retry, Decimal NAV/reconciliation,
source lineage/original/report bytes, and repeated restore idempotency. The
latest focused run passed all six tests against the disposable local PostgreSQL
16 server. Run it with:

```sh
STAGE4_RECOVERY_TEST_ADMIN_URL='postgresql+psycopg://<local-role>@127.0.0.1:<port>/postgres' \
  services/api/.venv/bin/pytest -q services/api/tests/test_recovery_archive.py
```

This is synthetic PostgreSQL evidence, not a DSQL/S3 backup test. DSQL export,
private S3 object access, AWS Backup, cross-service consistency under concurrent
production writes, retention, passphrase recovery, RTO/RPO, and a real
DSQL-to-local restore remain unverified. There is no automated schedule,
retention deletion, server export endpoint, or automatic local/cloud sync.
Operational instructions and gates are in the [Stage 4 recovery runbook](stage-4-recovery-runbook.md).


## S4.6 — Fail-closed release evidence and operations

The new offline verifier, app.release.stage4_gate, checks eight required
records: target configuration, immutable infrastructure plan, authenticated
HTTPS/private-S3 journey, complete live DSQL suite, cost/budget approval,
encrypted cloud recovery, operations rehearsal, and final production approval.
It binds records to the committed source, build, schema, fixture, configuration
contract, infrastructure source, and immutable image digest. Environment
configuration is fingerprinted separately for the DSQL test, synthetic launch,
and production. Each record must match the current expected hash supplied from
a separate reviewed target-configuration artifact; mutual agreement among
stale evidence records cannot establish current settings. Evidence older than
30 days, any missing record, any failure
or skip, stale hash, changed artifact, path outside the evidence bundle, or
mismatched configuration blocks the report. The report records evidence hashes,
the DSQL test cluster hash, gate results, and that no deployment was performed.
The DSQL configuration fingerprint includes its endpoint, roles, pool limits,
and bounded runtime settings. It binds the OIDC client secret and private owner
scope with an HMAC keyed by the session-signing secret without writing those
values into evidence. The verifier never calls AWS or applies infrastructure.

Non-DSQL evidence is a local JSON wrapper that references a hashed artifact.
Automated evidence requires positive test counts, zero failure/error/skip, and
no unverified gates. Approval evidence requires references to the actual review
record and approver; the tool verifies hashes but does not authenticate that a
person examined an artifact. The production approval remains a separate
human-controlled decision. The template command creates only an empty blocked
record; the check command never deploys. Run instructions and the evidence
schema are in the [Stage 4 operations runbook](stage-4-operations-runbook.md).

After the Stage 4 review fixes, focused config, auth, edge-header, storage,
release-gate, DSQL-evidence, migration-plan, and recovery tests passed 83 with
one credential-gated skip. The synthetic PostgreSQL recovery drill separately
passed, including interruption after a committed batch and staging-schema
publication. All thirteen live DSQL cases collected and skipped without the
explicit cluster opt-ins. Terraform 1.16.5 `fmt -check` and `validate` passed;
no AWS API or apply was run. Docker is not installed in the current environment,
so a built-image/fresh-volume smoke test remains unverified. Earlier full API
suite counts are historical and were not repeated for this fix set. No release
manifest was produced from actual cloud evidence because the required AWS target
and approved synthetic environment are not available.

### Current AWS service availability constraint

AWS's official [App Runner availability notice](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html),
checked 2026-10-03, states that AWS stopped accepting new App Runner customers
on 2026-03-31 and existing customers may continue. No target account has been
provided, so App Runner eligibility is unknown. The prepared Terraform now
requires a default-false explicit existing-customer confirmation before it
creates App Runner. Its API service and cost examples are usable only if the
target account is eligible. Otherwise, a separately reviewed runtime choice
and fresh whole-stack cost review are required. No substitute architecture is
selected. The prepared Terraform, earlier fake-input plans, and no-network
counts do not resolve account eligibility.

The operations runbook documents immutable builds, compatible app rollback,
forward-only DSQL repair/resume, pause and incident handling, retained-resource
inventory, and controlled exit. No HTTPS journey, cloud migration, App Runner
pause/resume, rollback, backup restore, teardown, or billing rehearsal ran.
AWS documents that App Runner pause reduces compute capacity to zero, loses
ephemeral application state, and resumes the last deployed version; the service
must be eligible and these behaviors still require a target-specific synthetic
rehearsal. Workers and personal-AI remain disabled.
