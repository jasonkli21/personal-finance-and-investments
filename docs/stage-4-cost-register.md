# Stage 4 AWS cost register

**Verified:** 2026-10-03 | **Status:** dated public list prices and bounded workload settings prepared; App Runner examples apply only to eligible existing customers; no target account, Region, workload measurement, monthly amount, or alert recipient selected

This register is a calculation worksheet, not a whole-stack forecast or spending approval. Prices, allowances, account eligibility, taxes, discounts, and credits must be checked in the target account and [AWS Pricing Calculator](https://calculator.aws/) before provisioning. Amounts below are public list-price examples from the linked official pages and may not apply to every Region or account.

## Resource and cost drivers

| Resource | Configured bound or usage driver | Cost treatment and control |
| --- | --- | --- |
| Aurora DSQL | One single-Region cluster; monthly DPUs and GB-month storage | AWS currently applies a monthly free tier of 100,000 DPUs and 1 GB-month, with billable overage. The US East (Ohio) page example lists $8 per million DPUs and $0.33/GB-month. Region and account eligibility must be confirmed; a free tier is not a cap. |
| App Runner | 0.25 vCPU, 1 GB, min/max one instance, concurrency 10; eligible existing accounts only | AWS stopped accepting new customers on 2026-03-31; confirm target-account eligibility before selecting this line item. For an eligible account, at the listed $0.007/GB-hour provisioned memory rate, 1 GB for 730 hours is about $5.11/month before active vCPU. Active vCPU is listed at $0.064/vCPU-hour: 0.25 vCPU adds about $0.016 per active instance-hour. 50/500/730 active hours yield illustrative totals of about $5.91/$13.11/$16.79, assuming one instance, 730 provisioned hours, listed rates, no additional memory, and one of the Regions with these unit prices. AWS bills a one-minute minimum for vCPU each time a provisioned instance begins active work. Pause the service during planned downtime; these calculations are not a measured forecast. |
| S3 private files + static assets | Original documents, encrypted exports, static build, PUT/GET/LIST requests and transfer | Storage, request, retrieval, and internet-transfer prices depend on Region, storage class, and usage. No lifecycle expiry is set for originals or exports: user financial records are retained until an operator-approved retention policy exists. Estimate retained GB and monthly request/egress volume in the target Region. |
| ECR | Last 20 immutable images retained by lifecycle policy; actual image sizes | AWS example lists $0.10/GB-month for private image storage and same-Region App Runner transfer at no cost. At 1 GB/image and all 20 retained, the illustrative storage component is $2/month; measure compressed stored size and recheck target Region. New-account credits are excluded from the forecast. |
| CloudFront | Request count and viewer egress by edge geography | Price depends on request type, geography, and selected features. S3-to-CloudFront origin transfer is listed as free; viewer transfer and HTTPS requests remain usage costs. Fetch a target-profile estimate after test traffic is measured. |
| Secrets Manager | Two referenced auth secrets plus API read volume | Listed unit price is $0.40 per secret-month plus $0.05 per 10,000 API calls. Two continuously stored secrets imply an illustrative $0.80/month before calls. The IaC consumes secret ARNs; secret values must not enter Terraform variables or artifacts. |
| CloudWatch | App/edge log ingestion, metrics, alarms, and retention | Price depends on log volume, metric/alarm configuration, and Region. App Runner's generated log groups are configured for 30-day retention by the post-create helper. Estimate volume using redacted synthetic traffic. |
| AWS Budgets | Optional one whole-account monthly cost budget with 50% actual, 80% forecast, and 100% actual email notifications | Monitoring/notifications are currently listed as free; credits are excluded so the configured threshold reflects post-credit charges, while discounts remain included by AWS default. The Terraform resource has no budget actions. Account-wide notifications include costs outside this stack, are subject to AWS billing data delay, and do not stop resources or limit spend. Email subscribers added since 2026-09-30 must complete AWS verification before receiving alerts. |
| External prerequisites / excluded resources | DNS, domain, ACM certificate, Terraform state, account support/tax; no NAT, ALB, PrivateLink, WAF, SQS, or AWS Backup in the prepared topology | Obtain separate estimates and ownership/retention decisions before adding any service. The absence of a topology item is not evidence that the account has no related charge. |

The Terraform variables set `MAX_IMPORT_ROWS=1000` by default and only permit 502–1000 until the largest current synthetic fixture is resized and reverified. Other injected limits are 5 MB per import file, 20 MB per private file, 40 PDF pages, an 8-second PDF parser timeout, three job attempts, pool size 3 with overflow 2, and one App Runner instance with concurrency 10. Production keeps background jobs and personal-AI disabled. These settings limit individual work, not aggregate account charges or arbitrary request volume.

## Transparent workload examples

These examples show only formula inputs, not a target deployment forecast:

| Profile | DSQL usage assumption | DSQL list-price example | App Runner active hours | App Runner list-price example |
| --- | --- | --- | ---: | ---: |
| Low | 50,000 DPUs, 0.5 GB-month | $0 within the published monthly allowance | 50 | ~$5.91 |
| At allowance | 100,000 DPUs, 1 GB-month | $0 within the published monthly allowance | 500 | ~$13.11 |
| High overage illustration | 1,100,000 DPUs, 20 GB-month | ~$14.27 using the Ohio page example: 1 million excess DPUs × $8/million + 19 excess GB × $0.33 | 730 | ~$16.79 |

The App Runner calculations assume one 0.25-vCPU/1-GB instance, 730 provisioned hours, and $0.007/GB-hour provisioned memory plus $0.064/vCPU-hour active CPU, with no scaling above one instance. DSQL's zero amount in the first two rows assumes an eligible account with the published monthly allowance available. These prices exclude S3, CloudFront, ECR, secrets, logs, support, tax, domain, state storage, data transfer, and any credits or negotiated discount. They do not add into a complete stack total.

AWS Budgets reports can lag: AWS says budget information is updated up to three times daily, typically 8–12 hours after the prior update, and billing data may take additional time to arrive. Set service alarms or operator checks where needed. Do not rely on budget alerts as emergency shutdown controls.

## Before infrastructure approval

The operator must provide the target AWS account and single data Region, confirm DSQL allowance eligibility, choose a whole-account monthly notification amount and verified recipient, estimate stored original/export size and retention, measure log and request volume, price CloudFront egress for expected users, price state/DNS/domain/support, and record the month-one and steady-state estimate. Revisit the estimate with actual Cost Explorer/billing data after a synthetic launch. Any increase in instance ceiling, storage retention, private endpoints, backup, queues, or log volume requires updating the register and reviewing spend again.

The optional Terraform budget intentionally defaults off because no alert amount or email recipient has been approved. Enabling it creates a whole-account USD cost budget through the `us-east-1` AWS Budgets control plane, independent of the selected data Region. A budget plan requires at least one valid email-shaped recipient (maximum 10). It excludes credits, sets actual thresholds at 50% and 100%, a forecast threshold at 80%, and creates no actions. AWS's 2026-09-30 change requires newly subscribed email recipients to verify delivery in the account. No recipient, budget amount, account query, or budget alert delivery test was supplied or run here.

## Pricing sources checked 2026-10-02; App Runner availability checked 2026-10-03

- [Aurora DSQL pricing](https://aws.amazon.com/rds/aurora/dsql/pricing/) — monthly free allowance, metered DPU/storage, and Ohio list-price example.
- [App Runner pricing](https://aws.amazon.com/apprunner/pricing/) — provisioned memory, active CPU/memory, and pause behavior; the prepared example is conditional on existing-customer eligibility.
- [App Runner availability change](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html) — new customers are no longer accepted beginning 2026-03-31; existing customers may continue.
- [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/) — storage, requests, data retrieval, and transfer components.
- [Amazon ECR pricing](https://aws.amazon.com/ecr/pricing/) — private image storage and same-Region transfer example.
- [CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/) — viewer transfer/request rates and usage-dependent pricing.
- [Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/) — stored secret and API-call rates.
- [AWS Budgets pricing](https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/) and [budget data timing](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html) — monitoring costs and alert update delay.
- [AWS Budgets email recipient verification](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-email-recipients.html) — account confirmation requirement for new recipients.
- [AWS Billing and Cost Management endpoints](https://docs.aws.amazon.com/general/latest/gr/billing.html) — AWS Budgets API endpoints, including `us-east-1`.
- [AWS Pricing Calculator](https://calculator.aws/) — required target-specific estimate tool.
