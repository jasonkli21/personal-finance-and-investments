# Security, GCP deployment and portability

Updated 2026-10-03. See [current state](current-state.md) for deployment readiness; this document specifies the security contract. See the [Stage 4 release](stage-4-release.md) and [operations](stage-4-operations-runbook.md) for dated evidence.

## Local and data ownership

PostgreSQL 16 and owner-only PrivateFileStore remain the local defaults. Compose publishes loopback ports. No external credentials or service calls are needed for manual/synthetic workflows. Originals are content-addressed, size bounded and hash verified, with private/no-store backend previews. Do not place originals or secrets in frontend bundles, fixtures, logs or public storage. Local/cloud data is independent; import/export is explicit.

Finance owns canonical data and deterministic validation/calculation. Cloud extraction is not authorized by deployment. Personal AI stays disabled pending transport, service/user identity, owner propagation and reviewed data use/retention/egress. No models receive real statements by default.

## Runtime and identity

Cloud Run serves the single FastAPI API; Firebase Hosting serves the SPA and rewrites /api/** before SPA fallback. Firebase forwards the original path, so backend ASGI transport strips /api before routes/auth. The Hosting edge forwards only __session; a signed envelope carries the existing separately signed OIDC transaction and opaque revocable DB session token. Local auth keeps its original cookies. The cloud envelope is Secure, HttpOnly, Path=/ and SameSite=Lax to allow OIDC redirects; OIDC state/nonce/PKCE, exact HTTPS issuer/audience/subject/scope checks, origin/CSRF checks and DB session expiry/revocation remain mandatory. No Firebase Auth dependency.

Firebase requires an externally invokable Cloud Run service. Infrastructure grants public service invocation only to the API; every /v1 finance route remains app-authenticated at both public and direct service URLs. Health routes reveal readiness only. Production disables interactive docs/OpenAPI. Never rely on a hidden service URL for authorization. Writes require the exact configured APP_PUBLIC_ORIGIN and reject cross-site requests. API responses remain no-store and logs redact query credentials, finance payloads and driver errors.

Neon uses ordinary verified PostgreSQL TLS and a runtime secret. Alembic uses an optional direct migration secret/role supplied only to the operator. GCP access uses ADC from dedicated API/worker identities, with bucket object-create/read and per-secret access. Runtime cannot change bucket policy or delete originals, and worker cannot invoke other jobs. No service-account JSON keys. Secret payloads never enter Terraform; pinned pre-existing versions are referenced. Protect operator credentials and Terraform state, which can contain owner/configuration metadata.

## Storage and jobs

GCS enforces uniform bucket access and public-access prevention; versioning and prevent_destroy protect originals. Retention/soft-delete/version storage incur costs and need an approved policy. The adapter creates only absent generations, verifies existing bytes on duplicate, reloads metadata/pins generation before bounded reads, checks hash/length and closes streams on failure. Preview remains authenticated and backend mediated; no signed public links.

Local polling is unchanged. Cloud API commits durable enqueue before invoking the bounded Cloud Run Job; repeated triggers compete under Finance's DB lease fence. Invocation failure returns a safe retry instruction and leaves the row durable. Repeat the identical upload or explicitly invoke the job to recover. A job executes at most 20 claim attempts within a 240-second claim loop; a final bounded unit may finish afterward, within the 300-second infrastructure timeout. No scheduler/queue is introduced. Backlog beyond the bounds, API interruption between enqueue/invoke and prolonged failures need operator drain/rehearsal; broader Stage 2 lifecycle acceptance remains partial.

## Costs and recovery

Scale API to zero, bound instances/pools, worker time/retries, request/row/file/parser sizes and log volume. Alerts are not spending caps; Neon bills separately from GCP. Review [costs](stage-4-cost-register.md) before provisioning and retain-resource costs before exit. No unrequested paid provider fallback.

Portable encrypted exports retain schema/scope checks, AEAD tamper detection, private file integrity, bounded batches and isolated resumable local restore. Bind the approved single personal scope; exclude sessions/credentials/unfinished worker state. Pause mutations/workers for a consistent Neon/GCS snapshot; retain immutable originals throughout export. Approve archive schedule, retention, passphrase custody, RPO/RTO and a real cloud-to-local drill before personal data. See [recovery](stage-4-recovery-runbook.md).

## Release gate

Commit exact source/tests, publish an immutable image and bind evidence to source/build/schema/fixtures/infrastructure/configuration/image. Missing, stale, failed or skipped tests block promotion. Required evidence includes real Neon migration/reconnect/concurrency, HTTPS OIDC/origin denial, unauthorized private APIs/direct service, anonymous GCS denial, authenticated preview, portable recovery, cost approval and operations rehearsal. No plan/apply/deploy occurred during the rearchitecture. Archived predecessor records retain their original dates and limits; use current docs for new work.
