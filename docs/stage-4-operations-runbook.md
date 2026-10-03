# Stage 4 gated release and operations runbook

**Status:** Local fail-closed gate and operator procedures prepared; no AWS
launch, release, pause, rollback, recovery, or teardown rehearsal has run
**Updated:** 2026-10-03

## Release evidence and promotion gate

The gate is an offline verifier. It does not deploy, apply Terraform, migrate a
database, upload assets, call AWS, or grant approval. A passing report means
every required evidence record was present, current, hash-matched, and passed
its declared checks. It does not authenticate the approver or replace the
separate human production authorization.

Build the API image and web assets from a committed source revision. Use the
immutable OCI SHA-256 digest, never a mutable tag. Keep build, image, Terraform
plan, test outputs, and evidence outside the repository in an access-controlled
release directory. Do not put credentials, environment dumps, raw statements,
full Terraform state, signed URLs, session cookies, or raw connector/test logs
in evidence. Evidence artifact paths are relative to the bundle directory and
must resolve to regular files within it.

After source is committed and the exact image digest is known, create a
mode-0600 blocked template:

    cd services/api
    export RELEASE_IMAGE_DIGEST='sha256:<reviewed-immutable-image-digest>'
    .venv/bin/python -m app.release.stage4_gate template \
      --output '/secure/release/stage4-evidence.json'

The template captures the current Git commit and source/build/schema/fixture,
configuration-contract, and infrastructure SHA-256 fingerprints. Its eight
gate entries are empty; it cannot pass. For each gate, add a relative path to
an evidence JSON file. Every non-DSQL evidence record must identify its gate,
result as passed, matching release fingerprint object, configuration context
and SHA-256, verification time, relative artifact path and artifact hash,
empty unverified-gate list, and false credentials/raw-logs flags. Automated
gates must include positive test counts with passed equal to total and zero
failures, errors, and skips. Approval gates must include a reviewed approval
reference and approver reference. DSQL evidence is the output from the
dedicated DSQL suite and is validated with that suite's stricter checker.

The required records are:

| Gate | Required context and evidence |
| --- | --- |
| target_configuration | Production account/Region, identity, service availability, domain/certificate, resource owner, and approved environment settings reviewed; attach the redacted target inventory/hash and approval record |
| immutable_infrastructure_plan | Exact source-matched, reviewed Terraform plan artifact and target; include App Runner existing-customer eligibility if that runtime is selected; no plan itself authorizes apply |
| authenticated_https_private_s3 | Synthetic HTTPS journey proves login, logout/revocation, cross-scope denial, authenticated original preview, private bucket access, bounded transfer, and no public file route |
| real_dsql_release_suite | Complete real-cluster evidence from app.release.dsql_evidence with every required matrix row implemented and zero skips |
| cost_and_budget_approval | Dated target-account whole-stack forecast after credits, service limits, selected monthly exposure, alert delivery, and explicit spend approval |
| encrypted_cloud_recovery | Approved isolated DSQL plus private S3 export, archive verification, and restore into a fresh isolated local PostgreSQL database; compare source lineage, hashes, and golden Decimal report |
| operations_rehearsal | Recorded synthetic launch, migration interruption/resume, compatible app rollback, pause/restore, resource inventory, and teardown rehearsal |
| production_release_approval | Human authorization referencing the exact immutable source, image, schema, target plan, cost approval, and other gate report hashes |

Check the bundle after all records are present and while the matching disposable
DSQL test configuration remains selected:

    .venv/bin/python -m app.release.stage4_gate check \
      --manifest '/secure/release/stage4-evidence.json' \
      --report '/secure/release/stage4-gate-report.json'

The checker requires the current source and image digest to match the bundle;
the DSQL evidence checker additionally requires its approved disposable
cluster, roles, region, backend configuration, and image to remain selected.
Evidence older than 30 days, from another build/schema/fixture/configuration
fingerprint, missing, skipped, failed, malformed, path-escaping, or changed
after hashing blocks the report. The report records release/evidence hashes,
per-gate outcomes, and the DSQL test-cluster identity hash. Both template and
report are private mode-0600 files. The report contains no deployment action.

The operator approval evidence is a human attestation. The verifier can prove
that a referenced artifact's bytes match its recorded digest and that the
review refers to this release; it cannot prove that a reviewer actually
examined the content or authenticate their identity. Retain approvals in the
chosen controlled review system. Do not fabricate local pass evidence to fill
missing cloud checks. With no target account, isolated DSQL cluster, private
bucket, budget, or approved production reviewer, the complete gate must remain
blocked.

Routine local CI remains offline. This repository has no credentialed automatic
deployment workflow, no long-lived cloud credentials, and no apply command.
Any later target-specific change must use narrowly scoped temporary operator
credentials and be approved separately after the full evidence report.

## Schema-safe release, rollback, and forward repair

1. Build once from the committed source and promote that same immutable OCI
   digest. Retain the prior compatible digest and its evidence. Static web
   assets must be from the same source release; do not publish a frontend whose
   API contract differs from the running backend.
2. Review the DSQL migration plan, schema fingerprint, app-role grants, and
   forward/rollback compatibility before any migration. Apply exactly one DDL
   statement per DSQL transaction, keep DML and index readiness steps separate,
   and record each completed step in the resumable ledger. Do not run a
   migration and switch application traffic until the full target schema and
   asynchronous indexes are ready.
3. If a migration fails, stop promotion. Inspect the ledger and actual schema,
   repair forward through a new reviewed migration or resume the recorded
   idempotent step. Never edit an applied migration, clear the ledger by hand,
   or assume a DSQL DDL sequence can roll back as a transaction.
4. Roll the application image back only when the prior digest is compatible
   with the current schema and the data written by the new application. If
   compatibility is unknown, pause ingress and prepare a forward repair using
   synthetic validation. Do not run destructive down-migrations or delete
   financial rows to make an old build start.
5. Keep worker and personal-AI settings disabled. Enabling a worker additionally
   requires its own real DSQL lease/retry evidence. Any retry must repeat only
   the bounded database unit, never the provider/file work.

No release or rollback was executed. The actual IAM roles, deploy commands,
compatibility matrix, cutover, health checks, and restore time must be verified
in the approved synthetic environment before the first production release.

## Pause, incident response, and controlled exit

For App Runner accounts confirmed eligible to use the service, AWS documents
pause as reducing service compute capacity to zero while retaining stored
service data. Pausing loses ephemeral application state. Resume returns the
last deployed version and does not automatically deploy a newer image. AWS
also notes that a service paused because of a code flaw cannot be updated until
it is resumed; keep a reviewed compatible rollback digest available and follow
the security response decision. See the [App Runner pause/resume procedure](https://docs.aws.amazon.com/apprunner/latest/dg/manage-pause.html)
and [availability notice](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html).

During a suspected data, auth, or integrity incident:

1. Stop initiating imports and manual refreshes. Keep personal-AI disabled and
   the worker disabled; if an actually approved worker exists, pause it through
   its reviewed control and wait for active database-only batches to settle.
2. Restrict API access or pause the selected compute service using the
   approved target-specific procedure. Verify the service is no longer
   processing requests. Stopping compute does not stop every charge or delete
   persistent data.
3. Preserve redacted request/job identifiers, migration ledger position,
   deployed image digest, schema fingerprint, cost status, and affected object
   hashes. Do not copy session tokens, account contents, statements, or
   connector credentials into the incident record.
4. Decide whether to restore service on the prior compatible image or keep it
   paused for forward repair. Require a successful health/security check and
   review the complete evidence for the chosen digest before reopening traffic.
5. If data integrity is in question, pause writes, export with the recovery CLI,
   verify the encrypted archive, and restore only into the isolated local
   recovery database. Do not overwrite or switch the everyday local database.

Before any planned shutdown, assess and record every resource. App Runner pause
stops its compute but retains stored service data. Deleting the App Runner
service is a different action and is not a general stack cleanup. Review the
following separately:

| Resource | Exit check |
| --- | --- |
| App Runner service and domain | Record service ARN/state and chosen immutable image; distinguish temporary pause from approved deletion |
| Aurora DSQL cluster | Confirm export/restore, backup/retention, deletion protection, and approved owner; never remove it as an app rollback |
| Private files and export S3 bucket | Inventory prefixes, object versions, hashes, lifecycle/retention, encryption, and continuing request/storage costs; preserve user originals and archives until explicit retention approval |
| Static S3 bucket and CloudFront | Record distribution, OAC, functions, cache invalidation state, origin access, and DNS; verify there is no private-file origin |
| ECR | Record retained immutable image digests and lifecycle policy; ensure the rollback image remains available before deleting older images |
| CloudWatch logs | Verify each generated API log group has the documented 30-day setting; confirm retention and any continuing storage |
| IAM and Secrets Manager | Inventory runtime and migration roles/policies, trust principals, secret ARNs, and revocation/rotation owner; do not put secret values in evidence |
| AWS Budgets | Record budget amount, alert thresholds, verified recipients, account scope, and notification delays; alerts do not cap charges |
| DNS, certificate, and Terraform state | Identify external owners, renewal/retention, protected remote state location, and recovery access; these are not all managed by this Terraform stack |

The prepared Terraform marks DSQL and both S3 buckets against accidental
destruction. Teardown requires a new reviewed change and deliberate removal of
protection after records/retention approval. Never use terraform destroy as an
application rollback. Stop or pause compute first, verify data recovery and
retained-resource owners, and review account charges after billing data has
settled. A synthetic rehearsal may remove only labeled test resources. Real
financial data deletion requires explicit user intent.

## Current operational evidence

No synthetic HTTPS deployment, real DSQL migration, AWS pause/resume, service
rollback, backup restore, teardown, or bill review has run. The App Runner
runtime is available only to eligible existing customers; the target account
eligibility is unknown. If ineligible, a runtime architecture and full-stack
cost review remain open. Stage 4 launch remains blocked until every required
gate above is supported by current target-bound evidence and separately
approved.
