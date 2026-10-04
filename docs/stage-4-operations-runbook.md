# Stage 4 operations and promotion

2026-10-03. Prepared procedures, no hosted rehearsal yet. No command here authorizes deployment without the user's target/budget approval.

## Provision and deploy

Use [infra/terraform/README.md](../infra/terraform/README.md). Bootstrap registry, private bucket, secret containers, identities and Firebase site with runtime disabled. Inject secrets outside Terraform. Build/push an exact-source image and supply its sha256 digest. Review the saved runtime plan and explicitly apply only that approved plan. Generate Firebase configuration from Terraform output; build SPA then deploy the matched configuration. Register the exact OIDC callback and bind the single owner with `python -m app.auth.bind_principal` after schema migration. Protect plan/state and private owner metadata.

## Evidence and release

`python -m app.release.neon_evidence run --evidence <private-path>` runs only explicitly opted-in disposable Neon tests. Set RUN_NEON_INTEGRATION=1, NEON_TEST_DATABASE=disposable, runtime/direct test URLs, RELEASE_IMAGE_DIGEST and EVIDENCE_CONFIGURATION_KEY (32+ secret characters). Never use production URLs. The runner requires committed sources and writes only hashes, cases/counts and result; it hides raw pytest/JUnit output.

With committed sources and the image digest, `python -m app.release.stage4_gate template --output <manifest>` creates a blocked template. Fill each gate with its reviewed artifact path/hash, verification timestamp, exact release fingerprint, independently computed environment configuration hash and tests or approval references. Required gates: target_configuration; immutable_infrastructure_plan; authenticated_https_private_gcs; real_neon_release_suite; cost_and_budget_approval; encrypted_cloud_recovery; operations_rehearsal; production_release_approval. Contexts are production, synthetic_launch and neon_test. Each manual record has evidence_version=1, matching gate_id/evidence_kind/configuration_context, result=passed, unverified_gates=[], credentials_recorded=false and raw_logs_recorded=false. Test records require positive counts with zero failures/errors/skips; approvals require reviewed reference and approver_reference.

Run `python -m app.release.stage4_gate check --manifest <manifest> --report <private-report> --expected-configurations <independent-context-hashes.json>`. Missing, skipped, stale (>30 days), changed source/schema/config/image or tampered artifacts block promotion. Independent hashes must come from actual reviewed target configurations, not copied from the submitted bundle. Offline structure tests cannot pass the runtime CLI gate. Manual artifacts are operator attestations, not authenticated cloud telemetry. Review them before use. No automatic deployment follows a pass.

## Logs and private operational evidence

Terraform sets the dedicated project’s `_Default` bucket retention to 30 days and excludes managed Cloud Run request URL logs from its default sink. Keep application route-template, timing and request-ID records; Uvicorn query-bearing access logging stays disabled. Review organization/custom sinks, Firebase edge logs and error reporting independently: the default exclusion does not govern other destinations. Before auth launch, inspect actual log receipts to prove callback queries, cookies, tokens and personal payloads are absent. [Cloud Run logging](https://docs.cloud.google.com/run/docs/logging) documents managed request logs and exclusions (checked 2026-10-03). No hosted log/privacy rehearsal is claimed.

## Reconnect, jobs and incident pause

Rehearse pooled app reconnection after Neon idle/suspend, pool exhaustion and safe DB-only retry/concurrent publication. Observe API request latency/503s and redacted request IDs. Test direct service auth and edge callback/cookie forwarding. Do not log connection strings or callback queries.

Jobs remain database rows. API enqueue commits before Cloud Run invocation; identical-upload retries safely re-trigger after failure. Each execution drains up to 20 attempts within a 240-second claim window; leases fence stale execution and cancellation. Bounded execution does not guarantee unlimited backlog recovery: operators inspect safe job status and execute the worker again if pending rows remain, including after interrupted enqueue/invoke, exhausted execution retries or timeout. Rehearse this before hosted PDF use. Never manually reset lease generations on a live worker.

Pause ingress or set maintenance policy, stop new document uploads/worker execution, wait for active bounded tasks, and preserve originals before an export/repair. Investigate using redacted correlation IDs. Do not rerun external parser/provider work inside DB retries or publish incomplete staging.

## Rollback, repair and exit

Roll back API and Hosting together to a previously approved image/static release only when that application is schema-compatible. Alembic revisions are forward history: append a repair migration rather than modifying applied files. Do not automatically downgrade a schema containing newer finance records. Export/verify first and restore into isolation for recovery; production replacement requires explicit data review.

Before exit inventory Neon branches/compute/storage/backups, GCS objects/versions/soft-delete, Artifact Registry images, Cloud Run revisions/jobs, Firebase site/custom domain, Secret Manager versions, identities/billing alerts and Terraform state. Pause new writes/executions, verify a portable archive and local restore, revoke runtime/service credentials, then review retained costs and deletion consequences. prevent_destroy/deletion_protection and force_destroy=false deliberately block blind destructive cleanup. Retention and data deletion need explicit decisions.
