# Stage 4 — GCP / Neon deployment plan

2026-10-03. Prepared tooling, unverified hosted launch. This is the deployment track for delivered finance behavior; it does not complete partial product stages. [ADR 0002](adr/0002-gcp-neon.md) and [migration audit](gcp-neon-migration.md) supersede predecessor infrastructure.

| Package | Implementation / gate |
| --- | --- |
| S4.1 Config/storage/auth | Standard psycopg, Alembic, optional direct migration URL, production TLS/HTTPS/OIDC validation, GCS FileStore, tested Firebase path/cookie transport. Local defaults preserved. |
| S4.2 Infrastructure | Terraform project services, Artifact Registry, private GCS, API/worker identities, Secret Manager containers, Cloud Run API/Job, Firebase site/config output. Bootstrap first, inject secrets and image, then reviewed runtime plan. Provider schema validation does not prove deployed IAM/routing. |
| S4.3 Real database evidence | Opt-in destructive disposable Neon branch tests and secret-free evidence runner. Fresh/populated migration, reconnect, retry and golden/batched/interrupted/concurrent import workflows. Missing/skipped cases block release. |
| S4.4 Cost policy | Target-specific GCP/Neon workload estimate and billing approval, scaling/connection envelope, storage/version/retention and alert-receipt proof. No hard-cap claim. |
| S4.5 Recovery/security | Existing encrypted portable snapshot/export and isolated local restore; hosted OIDC, anonymous denial, GCS generation/hash/privacy, scope and cloud-to-local recovery drill. |
| S4.6 Promotion/operations | Source/build/schema/fixture/infra/config/image-bound fail-closed manifest, explicit production approval and rollback/pause/exit rehearsal. No automatic deploy. |

## Execution sequence

1. Run pnpm check with disposable PostgreSQL and browser journeys. Review current partial/gated product findings.
2. Create a dedicated GCP project and disposable Neon branch using an approved budget. Keep production isolated from test URLs. Initialize/validate Terraform and inspect the bootstrap plan with enable_runtime=false.
3. Bootstrap only the approved plan. Populate Secret Manager outside Terraform; pin versions. Publish the exact-source API image to Artifact Registry and capture its digest. Register OIDC callback at the exact public /api/v1/auth/callback URL. Configure Neon runtime/migration roles and verified TLS URLs.
4. Run real Neon evidence with committed sources. Review runtime plan with enable_runtime=true, immutable digest and version bindings. Terraform never stores secret payloads.
5. Deploy reviewed runtime and Hosting configuration; run the synthetic HTTPS/auth/private-storage/jobs tests and record independent target configuration fingerprints. Bind and test the owner principal explicitly.
6. Pause writes/workers and export Neon/GCS into an encrypted archive. Restore to a fresh isolated local PostgreSQL target and reconcile totals/hashes. Approve RPO/RTO, retention and passphrase custody.
7. Assemble evidence bundle and run the Stage 4 verifier. Only a complete current bundle plus operator approval permits personal-data use. Skipped or unavailable cloud evidence remains pending.

## Required hosted journeys

SPA load and /api health/readiness; PKCE/nonce/state login/callback, wrong identity/origin denial, logout and revoked-session denial; direct Cloud Run financial routes cannot bypass auth; anonymous GCS fetch denied, authenticated private preview succeeds; durable PDF enqueue/duplicate execution/cancel/expired lease and delayed retries stay fenced; pooled reconnect after idle/suspend; interrupted enqueue/invoke and worker timeout/backlog drain; encrypted cloud export/local restore and application reconciliation. Include errors/restarts and prove safe redacted logging.

No queue, Firebase Auth, extra service, model integration or live market provider is introduced. See [operations](stage-4-operations-runbook.md), [recovery](stage-4-recovery-runbook.md), [costs](stage-4-cost-register.md) and [release](stage-4-release.md).
