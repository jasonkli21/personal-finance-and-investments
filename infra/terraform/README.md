# Single-region production infrastructure

This is **prepared IaC**, not permission to create AWS resources. No account,
region, public hostname, ACM certificate, OIDC issuer/subject, migration identity,
monthly spend envelope, or deployment approval has been supplied. Nothing in
this directory has been applied. `terraform.tfvars.example` contains fake values
for an offline plan only; never apply it.

## Selection and tradeoffs

Use one Aurora DSQL cluster and one AWS Region for the database, App Runner API,
ECR, and private S3 buckets. Use private S3 + CloudFront Origin Access Control
for the SPA, with the authenticated FastAPI service as a second HTTPS origin.
App Runner runs the existing OCI image directly, so the API keeps its normal
ASGI/SQLAlchemy connection lifecycle and bounded PDF parsing without a new
Lambda adapter or a long-lived EC2 operating-system/patching responsibility.
App Runner's default egress reaches the public DSQL endpoint without a VPC,
NAT gateway, ALB, or PrivateLink endpoint. AWS documents that default egress is
public and that App Runner's public ingress is reachable from the internet;
route authorization therefore remains mandatory at the API origin.

This is a runtime fit decision, not a measured performance result. Lambda could
reduce idle compute for a low-traffic API, but needs a Lambda-compatible ASGI
entry point/API Gateway integration and evidence for cold starts, PDF memory and
time bounds, pooled connections, token renewal, and job behavior. No compatible
Lambda benchmark has been run. Small EC2 offers direct control, but adds
instance patching and a continuously billed host; common HTTPS ingress choices
such as ALB add further fixed/usage costs. Before production, run the synthetic
HTTPS journey and representative bounded file/import smoke checks, review
CloudWatch/App Runner metrics and actual account pricing, and resize only after
that evidence. Initial App Runner sizing is 0.25 vCPU / 1 GB, one minimum and
maximum instance, and at most 10 concurrent requests. These are adjustable
operator inputs and are not a spending cap or an availability commitment.

## Resource inventory

| Scope | Resources | Boundary |
| --- | --- | --- |
| Regional data | One deletion-protected Aurora DSQL cluster; separate private-files and static-assets S3 buckets | No multi-region DSQL, public bucket, user-data sync, or conventional RDS subnet topology |
| API delivery | Immutable ECR repository; App Runner service and one-instance autoscaling config | Image is pinned by SHA-256 digest; auto-deployment is disabled; worker stays off |
| IAM | ECR image-pull role, scoped App Runner instance role, separate operator migration role | Runtime role has only DSQL `DbConnect`, private object reads/writes, configured secret reads, and bucket listing; migration role alone gets `DbConnectAdmin` on this cluster and trusts one exact supplied principal |
| Web edge | CloudFront distribution, OAC, two small path functions, bounded cache/origin/response policies | Static origin is private; API behavior forwards cookies/OIDC query and CSRF headers and sets zero cache TTL |
| Operator-owned prerequisites | DNS record, validated ACM certificate in `us-east-1`, identity-provider registration and two Secrets Manager values | Kept outside this stack because the owner's DNS/provider/identity choices are not known |

There is no queue or remote worker resource because the implemented worker is
not DSQL-lease verified. No NAT, ALB, VPC, PrivateLink, WAF, or customer-managed
KMS key is included; add one only for a documented requirement and cost review.
The optional `monthly_cost_budget_usd` creates one whole-account AWS Budgets
notification in the `us-east-1` billing control plane, with actual alerts at
50%/100% and a forecast alert at 80%. It defaults off because no monthly
exposure or email recipient has been approved. If enabled, set both it and at
least one `cost_alert_email_addresses` recipient. Its cost types exclude credits
to make the threshold reflect post-credit spend. AWS began requiring new
recipients to confirm email subscriptions on 2026-09-30; confirm the AWS email
subscription after provisioning. The account-wide budget can include costs
outside this Terraform stack, notifications may lag billing data by hours, and
the resource has no actions or spending cap. Keep budget email/other operator
inputs out of shared plans and protect Terraform state.
CloudFront is global. Its ACM certificate is required in `us-east-1`; regional
data and API resources use the explicitly supplied `aws_region`. DNS remains
external and must point `app_domain_name` to the CloudFront output.

App Runner exposes a direct public service URL in addition to CloudFront. This
topology does not claim origin hiding or WAF protection: callers may bypass the
edge. The same app issuer/subject/session/scope checks protect every financial
API route and private file operation at either hostname. Only the minimal
health routes are unauthenticated. Do not migrate private data until the direct
origin synthetic test confirms these controls.

Production request work is bounded at one App Runner instance, concurrency 10,
1 GB/0.25 vCPU, 1,000 rows per import, 5 MB import files, 20 MB private files,
40 PDF pages, an 8-second parser timeout, and three job attempts. The worker and
personal-AI gates remain off. The import-row variable only permits 502–1,000
until the largest current synthetic release fixture is resized and reverified.
These are local controls and do not cap aggregate AWS spend. No S3 expiry is
configured for private originals or exports: user data retention needs an
explicit policy and recovery plan. The ECR lifecycle retains the newest 20
immutable images. See the [dated cost register](../../docs/stage-4-cost-register.md)
for official unit-price sources, workload calculations, and the target estimate
gate.

## Ordered preparation and plan

1. Install Terraform `1.16.5` and run `terraform init` in this directory. The
   exact AWS provider `6.67.0` and Random provider `3.7.2` are pinned in
   `versions.tf`; `.terraform.lock.hcl` records the registry checksums verified
   by `terraform init`. Provider versions were checked 2026-10-02. `terraform
   init` does not apply resources.
2. Copy `terraform.tfvars.example` to the ignored `terraform.tfvars` and replace
   every fake value with the exact operator-approved account, region, OIDC,
   subject/scope, domain, certificate, IAM principal, secret ARNs, role name,
   and actual image digest. Do not put secret values in this file; the file
   accepts only Secrets Manager ARNs for the two auth secret values.
3. Inspect the explicit target and planned inventory with
   `terraform plan -var-file=terraform.tfvars -out=stage4.tfplan`, then review
   `terraform show -no-color stage4.tfplan`. No plan is permission to apply.
   `terraform.tfvars.example` is only an obvious fake-input sample. Do not use
   it for a real target plan or apply. A local no-network structural plan using
   fake credentials, `-refresh=false`, a temporary ignored skip-STS override,
   and a closed localhost proxy produced 18 foundation resources; enabling
   `deploy_api_service` produced 30 total resources. With the optional budget
   enabled, a separate no-refresh plan produced 19 foundation resources; the
   recipient-less configuration failed the Terraform precondition as intended.
   The same one-resource budget increment applies to the full plan if selected.
   These plans were saved only
   under `/private/tmp`, do not represent an AWS account or validate resource
   availability, and cannot satisfy a target-specific review gate. The
   temporary override was removed after the checks.
4. Before any approved apply, configure a dedicated encrypted/locked Terraform
   state backend outside the finance data bucket, validate its access and
   recovery, and get explicit AWS target and budget approval. The default local
   state is ignored by Git but is not an acceptable shared production state.
5. Apply the approved foundation as a distinct reviewed action. The first pass
   creates DSQL, buckets, ECR, and scoped IAM but no API or CloudFront. Initialize
   the DSQL schema and exact app-role grants through the separately reviewed
   migration identity. Build/test the API image, push it to the immutable ECR
   repository, and record its digest. Then set `deploy_api_service=true`, replace
   the placeholder digest and OIDC/domain inputs, plan again, and review before
   a separately authorized apply creates App Runner and CloudFront.
6. Complete the identity callback registration at
   `https://<app_domain_name>/api/v1/auth/callback`, DNS/TLS, principal mapping,
   log-retention setup, app-role grant, and full launch gates in
   [`../../docs/stage-4-release.md`](../../docs/stage-4-release.md) before private data.

The initial plan may show unknown generated IDs and URLs. Do not copy terraform
state, plans, App Runner environment, OIDC subject/scope, secret ARNs, signed
tokens, or logs into public evidence. Review the readable resource plan with
identifiers redacted. `aws_dsql_cluster.identifier` is converted to the
documented `<cluster-id>.dsql.<region>.on.aws` public endpoint format; TLS must
remain `verify-full` in the application connector.

## Image, static files, and operations

The repository ECR image must be built from `services/api/Dockerfile`, which
contains the Alembic files and runs as UID/GID 10001. Use a reviewed immutable
digest, never `latest` or a mutable tag. The App Runner service has no CI push
connection and no automatic deployment. Static Vite assets are uploaded only
after an approved release to the bucket in Terraform output; invalidate
`/index.html` after review. CloudFront rewrites `/api/...` to FastAPI `/...` and
rewrites extensionless *static* routes to `/index.html`, avoiding global 403/404
rewrites that would corrupt API denial responses.

App Runner chooses its log group names using a generated service ID, so
Terraform cannot predeclare those names. Run the log-retention helper in
[`../../scripts/stage4/set-apprunner-log-retention.sh`](../../scripts/stage4/set-apprunner-log-retention.sh)
after creation and after each replacement; it sets 30-day retention on both
App Runner log groups and verifies the setting. App logs must remain redacted.
That post-create step is a launch gate, not a default AWS retention guarantee.

Deletion protection and `prevent_destroy` protect DSQL and both buckets. A
planned teardown must first pause API/worker work, export and restore synthetic
data, review backups/versions/logs/ECR/DNS/CloudFront, record retained-resource
owners and continuing costs, and then deliberately remove guards in a reviewed
change. Do not run `terraform destroy` as rollback. See Stage 4.6 operations.

## Current source checks (2026-10-02)

- [AWS App Runner outbound networking](https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html): default public endpoint egress; custom VPC egress requires network paths to public AWS APIs.
- [AWS App Runner IAM roles](https://docs.aws.amazon.com/apprunner/latest/dg/security_iam_service-with-iam.html): `build.apprunner.amazonaws.com` for ECR access and `tasks.apprunner.amazonaws.com` for runtime; `ecr:GetAuthorizationToken` requires `Resource: *`.
- [AWS App Runner ingress](https://docs.aws.amazon.com/apprunner/latest/dg/network-incoming.html): public endpoint is the default; private ingress requires PrivateLink.
- [AWS Aurora DSQL endpoint and auth](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/SECTION_authentication-token.html): endpoint uses `<cluster-id>.dsql.<region>.on.aws`; [authorization](https://docs.aws.amazon.com/aurora-dsql/latest/userguide/authentication-authorization.html) separates `DbConnect` from `DbConnectAdmin`.
- [AWS App Runner logs](https://docs.aws.amazon.com/apprunner/latest/dg/monitor-cwl.html): generated service-ID log groups default to CloudWatch's indefinite retention unless an operator sets retention.
- [HashiCorp AWS provider](https://github.com/hashicorp/terraform-provider-aws/releases): release `6.67.0` published 2026-09-30; `aws_dsql_cluster` supports deletion protection and optional multi-region configuration, which this stack omits.
- [Terraform releases](https://releases.hashicorp.com/terraform/): stable `1.16.5` when checked.

Recheck provider compatibility, AWS service availability and prices in the
actual account before a plan is approved. No account API was queried and no
runtime benchmark, terraform apply, image push, or service deployment has run.
