# GCP / Neon cost register

Reviewed 2026-10-03. No target account estimate or bill has been approved; deployment remains gated. Local operation has no recurring provider charge. Free allowances are plan/region/account dependent and can change; never promise permanently free hosting. Alerts are not hard spending caps.

| Component | Cost input to record before apply | Official source checked |
| --- | --- | --- |
| Cloud Run API | region, request billing, active CPU/GiB seconds, requests, egress; min 0 / max 2, concurrency 8 | [Cloud Run pricing](https://cloud.google.com/run/pricing) |
| Cloud Run Jobs | executions × task CPU/memory/time, retries and duplicate triggers; task 1, 300-second timeout, one infra retry | [Cloud Run pricing](https://cloud.google.com/run/pricing) |
| GCS | live/version/soft-delete/backup GiB-month, read/write operations, recovery/egress | [Storage pricing](https://cloud.google.com/storage/pricing) |
| Firebase Hosting | required billed project plan, stored SPA bytes and transferred bytes, dynamic backend usage | [Firebase pricing](https://firebase.google.com/pricing) |
| Artifact Registry | retained image storage/scanning/transfer and old image policy | [Registry pricing](https://cloud.google.com/artifact-registry/pricing) |
| Secret Manager / logs | active versions/access operations, log volume/retention/export | [Secrets pricing](https://cloud.google.com/secret-manager/pricing), [Observability pricing](https://cloud.google.com/stackdriver/pricing) |
| Neon (separate bill) | selected plan, compute hours/scaling/suspend, storage/history/branches, connections and transfer | [Neon plans](https://neon.com/pricing); target terms must be independently verified before provisioning |
| Billing alerts | project filter and confirmed billing contacts; alert receipt/latency rehearsal | [Budget behavior](https://docs.cloud.google.com/billing/docs/how-to/budgets) |

For an illustrative workload, record N API requests × measured billable duration, J worker executions (including retries) × measured task duration, B retained object/version/archive bytes and I retained image bytes. Multiply each by the selected region's current unit price and apply verified eligible allowances once across the actual billing account. Include cross-provider Neon traffic. Use both normal and incident/backlog/restore envelopes; scale-to-zero and max instances do not limit total monthly traffic or parallel Job executions.

Terraform's optional project budget alerts at 50/90/100% of the selected reviewed dollar amount; no automatic spending shutdown is configured. Verify billing account/project linkage and recipient receipt. Neon alerts/limits are independent. Before apply, capture actual target plan/region/currency/unit-price date, current usage/eligibility, monthly forecast, incident/restore allowance, alert contacts, retained-resource exit inventory and operator approval in the release artifact. Numeric estimates cannot be inferred from sample tfvars or historical bills.

The predecessor dated cost register is preserved in [history](history/pre-gcp-neon/stage-4-cost-register.md), as superseded evidence only.
