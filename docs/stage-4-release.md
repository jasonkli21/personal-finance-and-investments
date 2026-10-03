# Stage 4 release evidence

**Status:** S4.1 configuration/storage/auth and S4.2 declarative resource inventory prepared locally; no AWS resources provisioned and live DSQL remains unverified
**Updated:** 2026-10-02

This record distinguishes locally implemented release machinery from credentialed launch evidence. A passed SQLite/PostgreSQL test or skipped AWS suite does not satisfy the real Aurora DSQL, bucket-policy, cost-approval, recovery, or HTTPS launch gates.

## S4.1 — Production configuration, storage and authentication

The API now accepts explicit `development`, `test`, and `production` settings. Production startup fails closed unless it has HTTPS origin, the single-person authentication configuration, Aurora DSQL, a separate migration role, private S3 storage, and secure cookies. It rejects demo mode, the local worker before DSQL lease evidence, and collision between private and static bucket names. Local PostgreSQL and filesystem storage remain defaults for offline operation.

All private file consumers now share the `FileStore` interface. The local store enforces configured read/write bounds, owner-only permissions, generated content-addressed keys, and SHA-256 verification. The S3 adapter uses a generated SHA-256 key, conditional create, explicit server-side encryption, bounded reads/writes, and hash/size verification. It does not return S3 URLs; authenticated API routes stream file content through the backend. IAM policy, S3 public-access controls, encryption-key policy, region availability, and actual transfer behavior are not yet verified in AWS.

Authentication uses a provider-neutral OpenID Connect authorization-code flow with PKCE `S256`. Authlib verifies callback state, code challenge, ID-token signature against discovered JWKS, issuer, audience, expiry, and nonce; the app then requires the configured exact `(issuer, subject)` and server-owned personal scope. OIDC uses a short-lived signed `HttpOnly`, `Secure`, `SameSite=Lax` transaction cookie for the cross-site callback. A verified login creates a separate opaque `HttpOnly`, `SameSite=Strict` session cookie; only its SHA-256 digest is stored. The server checks active subject, issuer, scope, revocation, and expiry on every `/v1` request. Mutations require the configured `Origin` and reject cross-site fetches. Logout revokes the database session. Redacted login/logout audit rows carry the server-generated request correlation ID. The SPA waits for session validation, gates all finance workspaces behind sign-in, clears React Query data on 401/logout, and provides sign-out. `/health` and `/health/ready` expose only status. The OIDC provider/client, callback registration, and stable subject are operator settings; no live provider is configured or exercised.

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
| S4.2 | Terraform lockfile, provider schema validation, static policy guardrails, and fake-input no-network plans prepared | Explicit account/region/domain/certificate/image/identity/budget inputs, target-specific reviewed plan, runtime smoke/benchmark, and approved apply |
| S4.3 | Nine-case real-DSQL suite and fail-closed evidence runner prepared; all nine cases skip without explicit opt-in | Execute against an approved isolated DSQL cluster and pass with zero skipped tests; separately close the populated-upgrade, interrupted-migration, token-expiry, and real DSQL OCC-gap evidence |
| S4.4 | Official allowance/pricing source rechecked 2026-10-02 | Account-specific whole-stack forecast, approved spend exposure, budget routing test |
| S4.5 | Pending | Encrypted portable export and isolated restore with tamper/interruption negatives |
| S4.6 | Pending | Approved gated release, synthetic launch, rollback/pause/teardown rehearsal and retained-resource inventory |

The published DSQL allowance is 100,000 DPUs plus 1 GB-month of storage per month, with billable overages; it is not a whole-stack cap. AWS account, target region, identity, alert recipient, monthly exposure, and deployment approval have not been supplied. No infrastructure apply, cloud test, data transfer, push, or deployment is authorized by this release record.

## S4.2 — Declarative single-region infrastructure preparation

[`infra/terraform`](../infra/terraform/README.md) selects one DSQL cluster,
private statement/export S3, separate private static S3 behind CloudFront OAC,
an immutable ECR image, App Runner, and scoped runtime and operator migration
roles. The API/edge resources default off. A first reviewed foundation apply
would create the ECR repository before an operator builds and pushes an image;
the second reviewed plan would use its immutable digest and enable App Runner
and CloudFront. No stage has been applied here.

The current choice is App Runner for the existing containerized ASGI API,
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

CloudFront forwards cookies, OIDC callback query strings, and CSRF-relevant
headers to an HTTPS-only API origin with zero cache TTL. A viewer-request
function removes the public `/api` prefix before FastAPI; a separate static-only
function handles SPA routes, so API error statuses remain intact. DNS, the
validated `us-east-1` ACM certificate, identity-provider registration, secrets,
Terraform remote state backend, resource owner, AWS account/region, exact
subject/scope, and monthly budget remain operator inputs.

AWS App Runner creates log groups with generated service IDs and they default to
indefinite CloudWatch retention. The checked helper sets and verifies 30 days;
doing so after creation/replacement is a mandatory launch gate. Terraform
`1.16.5` `fmt` and `validate` passed. `.terraform.lock.hcl` records HashiCorp
AWS provider `6.67.0` and Random provider `3.7.2` checksums fetched from their
official registry. Fake-input no-network plans described 18 foundation
resources and 30 total resources when App Runner/CloudFront were enabled; they
used a temporary local skip-STS override, fake credentials, no refresh, and a
closed localhost proxy, and were saved outside the repository. They do not prove
the actual account's resource availability, quota, costs, identity, or DNS/TLS.
No account API was queried, no App Runner runtime was benchmarked, and there has
been no real target plan, Terraform apply, image build/push, DNS/TLS test, DSQL
connection, or AWS resource call.
Local guardrails are executable with:

```sh
python3 scripts/stage4/test_infra_contract.py
bash -n scripts/stage4/set-apprunner-log-retention.sh
```

## S4.3 — Real Aurora DSQL suite and evidence gate

The gated suite covers the complete versioned migration plan and representative
synthetic schema/UUID/`NUMERIC`/JSONB round trips, current tax/event/auth
tables, auth/session constraints, fresh app-role IAM/TLS reconnect, a real
competing-write retry, snapshot replacement/history, the 502-row fund import,
hidden interrupted staging, concurrent publication, and golden report values.
The application role and migration role are supplied separately. The new auth
checks exercise the deployed migration-0015 tables using only synthetic IDs.
Every feature case has scoped cleanup and does not target local or user data.

`app.release.dsql_evidence` is the promotion runner. It requires the exact
`RUN_DSQL_INTEGRATION=1`, `DSQL_TEST_CLUSTER=disposable`,
`DATABASE_BACKEND=aurora_dsql` opt-in, a DSQL endpoint, AWS region, and distinct
non-admin application/migration roles. It captures pytest/JUnit only in a
temporary directory, never prints or saves raw output, and emits a mode-0600
summary bound to source commit, application build, Alembic/DSQL schema plan,
sanitized configuration, fixture, immutable OCI image digest, and hashed cluster
identity. The `check` command requires the same runtime configuration and image
digest to still be selected. Missing required cases, a nonzero test result, or
any skip writes failed/blocked evidence; `check` rejects skips, failures,
incomplete suites and stale fingerprints. The current report also carries explicit blockers for populated
previous-schema upgrade, induced migration interruption/resume, 15-minute IAM
token-expiry reconnection, and a configured safe-batch-limit failure; even a
clean run of the available nine cases cannot pass the promotion check until
those matrix rows are implemented and evidenced.

Run only after supplying credentials to an explicitly approved isolated,
disposable test cluster and confirming its spend envelope:

```sh
export RUN_DSQL_INTEGRATION=1
export DSQL_TEST_CLUSTER=disposable
export DATABASE_BACKEND=aurora_dsql
# Also set AWS_REGION, the DSQL endpoint and distinct scoped roles, and
# RELEASE_IMAGE_DIGEST to the reviewed source-matched sha256 OCI image digest.
uv run --directory services/api --locked python -m app.release.dsql_evidence \
  run --evidence /secure/operator/path/dsql-evidence.json
uv run --directory services/api --locked python -m app.release.dsql_evidence \
  check /secure/operator/path/dsql-evidence.json
```

The test harness can verify a newly opened IAM/TLS connection after disposing
the old pool, but does not wait 15 minutes to demonstrate token-expiry
reconnection. It also does not yet provide a safe real-cluster populated
previous-version upgrade, induced mid-migration interruption/resume, or a
reliably induced native DSQL OCC conflict on demand. Those remain explicit
launch evidence gaps; the existing OCC case coordinates competing transactions
and passes only if DSQL itself reports the retryable conflict. No DSQL cluster
was configured here: a direct default invocation reported all nine gated cases
skipped, and no evidence record was issued. Local evidence-gate tests prove
that skip/failure/stale-schema records cannot be promoted. Live DSQL therefore
remains **unverified**.
