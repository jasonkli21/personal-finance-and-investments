# Stage 4 release evidence

**Status:** S4.1 configuration, storage, and personal authentication prepared locally; no AWS resources provisioned and live DSQL remains unverified
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
| S4.2 | Pending | Explicit account/region decision, reviewed declarative plan, and no-apply IAM/resource checks |
| S4.3 | Pending real-cluster execution | Full current-schema DSQL suite with dated, secret-free evidence |
| S4.4 | Official allowance/pricing source rechecked 2026-10-02 | Account-specific whole-stack forecast, approved spend exposure, budget routing test |
| S4.5 | Pending | Encrypted portable export and isolated restore with tamper/interruption negatives |
| S4.6 | Pending | Approved gated release, synthetic launch, rollback/pause/teardown rehearsal and retained-resource inventory |

The published DSQL allowance is 100,000 DPUs plus 1 GB-month of storage per month, with billable overages; it is not a whole-stack cap. AWS account, target region, identity, alert recipient, monthly exposure, and deployment approval have not been supplied. No infrastructure apply, cloud test, data transfer, push, or deployment is authorized by this release record.
