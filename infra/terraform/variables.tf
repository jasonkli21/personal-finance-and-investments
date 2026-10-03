variable "aws_account_id" {
  description = "Explicit target account ID; used to scope IAM policies without account discovery calls."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be exactly 12 digits."
  }
}

variable "aws_region" {
  description = "One supported Aurora DSQL and App Runner Region, explicitly selected by the operator."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be an AWS Region identifier."
  }
}

variable "resource_name_prefix" {
  description = "Short lowercase prefix used for generated names."
  type        = string
  default     = "personal-finance"

  validation {
    condition     = length(var.resource_name_prefix) >= 3 && length(var.resource_name_prefix) <= 28 && can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.resource_name_prefix))
    error_message = "resource_name_prefix must be 3-28 lowercase letters, digits, or internal hyphens."
  }
}

variable "resource_owner_tag" {
  description = "Human-readable owner tag for resource inventory and billing review."
  type        = string

  validation {
    condition     = length(trimspace(var.resource_owner_tag)) > 0 && length(var.resource_owner_tag) <= 128
    error_message = "resource_owner_tag must be a non-empty value of at most 128 characters."
  }
}

variable "app_domain_name" {
  description = "Operator-owned public hostname for CloudFront. DNS remains externally managed."
  type        = string

  validation {
    condition     = length(var.app_domain_name) <= 253 && can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", lower(var.app_domain_name)))
    error_message = "app_domain_name must be a DNS hostname without a scheme or path."
  }
}

variable "cloudfront_acm_certificate_arn" {
  description = "Previously issued ACM certificate ARN in us-east-1 covering app_domain_name. Terraform does not create or validate the certificate."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:acm:us-east-1:[0-9]{12}:certificate/[0-9a-fA-F-]{36}$", var.cloudfront_acm_certificate_arn))
    error_message = "CloudFront requires a certificate ARN in us-east-1."
  }
}

variable "api_image_digest" {
  description = "Immutable sha256 digest of the API image already pushed to the managed ECR repository before App Runner creation."
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "api_image_digest must be a complete sha256 digest, never a mutable tag."
  }
}

variable "auth_issuer_url" {
  description = "Exact HTTPS OIDC issuer URL registered with the selected identity provider."
  type        = string

  validation {
    condition     = can(regex("^https://[^/]+(/[^?#]*)?$", var.auth_issuer_url))
    error_message = "auth_issuer_url must be an HTTPS issuer URL without a query or fragment."
  }
}

variable "auth_client_id" {
  description = "OIDC confidential-client ID registered for the exact CloudFront callback URL."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.auth_client_id) > 0 && length(var.auth_client_id) <= 512
    error_message = "auth_client_id must contain 1-512 characters."
  }
}

variable "auth_client_secret_arn" {
  description = "Exact Secrets Manager ARN whose value is injected as AUTH_CLIENT_SECRET."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex(format("^arn:aws:secretsmanager:%s:%s:secret:.+$", var.aws_region, var.aws_account_id), var.auth_client_secret_arn))
    error_message = "auth_client_secret_arn must be a Secrets Manager ARN in the selected account and Region."
  }
}

variable "auth_session_signing_key_secret_arn" {
  description = "Exact Secrets Manager ARN whose value is injected as AUTH_SESSION_SIGNING_KEY."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex(format("^arn:aws:secretsmanager:%s:%s:secret:.+$", var.aws_region, var.aws_account_id), var.auth_session_signing_key_secret_arn))
    error_message = "auth_session_signing_key_secret_arn must be a Secrets Manager ARN in the selected account and Region."
  }
}

variable "auth_allowed_subject" {
  description = "Exact stable OIDC subject authorized for this personal deployment."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.auth_allowed_subject) > 0 && length(var.auth_allowed_subject) <= 200
    error_message = "auth_allowed_subject must contain 1-200 characters."
  }
}

variable "auth_personal_scope_id" {
  description = "Server-owned personal scope ID mapped to the allowlisted issuer/subject."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.auth_personal_scope_id) > 0 && length(var.auth_personal_scope_id) <= 64
    error_message = "auth_personal_scope_id must contain 1-64 characters."
  }
}

variable "app_database_role" {
  description = "Pre-created least-privilege Aurora DSQL application database role; never admin."
  type        = string

  validation {
    condition     = length(var.app_database_role) > 0 && length(var.app_database_role) <= 63 && lower(var.app_database_role) != "admin"
    error_message = "app_database_role must be a non-empty non-admin role name of at most 63 characters."
  }
}

variable "migration_database_role" {
  description = "Separate DSQL database role used by operator-run schema migrations; AWS-created admin is the initial default."
  type        = string
  default     = "admin"

  validation {
    condition     = length(var.migration_database_role) > 0 && length(var.migration_database_role) <= 63
    error_message = "migration_database_role must contain 1-63 characters."
  }
}

variable "migration_trusted_principal_arn" {
  description = "Exact IAM user/role ARN allowed to assume the separate DSQL migration role."
  type        = string

  validation {
    condition     = can(regex("^arn:[^:]+:iam::[0-9]{12}:(user|role)/.+$", var.migration_trusted_principal_arn))
    error_message = "migration_trusted_principal_arn must be an exact IAM user or role ARN."
  }
}

variable "api_cpu" {
  description = "App Runner instance CPU sizing; initial 0.25 vCPU is a conservative unbenchmarked starting point."
  type        = string
  default     = "0.25 vCPU"

  validation {
    condition     = contains(["0.25 vCPU", "0.5 vCPU", "1 vCPU", "2 vCPU", "4 vCPU"], var.api_cpu)
    error_message = "api_cpu must be a supported App Runner CPU size."
  }
}

variable "api_memory" {
  description = "App Runner instance memory; 1 GB gives the Python API headroom for bounded document parsing."
  type        = string
  default     = "1 GB"

  validation {
    condition     = contains(["0.5 GB", "1 GB", "2 GB", "3 GB", "4 GB", "6 GB", "8 GB", "10 GB", "12 GB"], var.api_memory)
    error_message = "api_memory must be a supported App Runner memory size."
  }
}

variable "api_max_concurrency" {
  description = "Maximum concurrent requests per instance; requires smoke and load review before increasing."
  type        = number
  default     = 10

  validation {
    condition     = var.api_max_concurrency >= 1 && var.api_max_concurrency <= 100
    error_message = "api_max_concurrency must be between 1 and 100."
  }
}

variable "api_max_import_rows" {
  description = "Hard per-upload row cap injected into the API; 502 preserves the largest existing synthetic import fixture."
  type        = number
  default     = 1000

  validation {
    condition     = var.api_max_import_rows >= 502 && var.api_max_import_rows <= 1000
    error_message = "api_max_import_rows must be between 502 and 1000 until the release fixture is resized and reverified."
  }
}

variable "monthly_cost_budget_usd" {
  description = "Optional whole-account AWS monthly cost alert threshold. Alerts do not cap usage or apply account actions."
  type        = number
  default     = null

  validation {
    condition     = var.monthly_cost_budget_usd == null || (var.monthly_cost_budget_usd >= 1 && var.monthly_cost_budget_usd <= 1000000)
    error_message = "monthly_cost_budget_usd must be unset or between USD 1 and USD 1,000,000."
  }
}

variable "cost_alert_email_addresses" {
  description = "Explicit email recipients for the optional account budget; AWS requires subscribers to verify notifications and limits each notice to 10 addresses."
  type        = set(string)
  default     = []
  sensitive   = true

  validation {
    condition     = length(var.cost_alert_email_addresses) <= 10 && alltrue([for address in var.cost_alert_email_addresses : can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", address))])
    error_message = "cost_alert_email_addresses must contain at most 10 valid email-shaped addresses."
  }
}

variable "job_worker_enabled" {
  description = "Must remain false until the real DSQL job lease/retry gate has passed."
  type        = bool
  default     = false

  validation {
    condition     = var.job_worker_enabled == false
    error_message = "Cloud worker resources are not implemented or released; keep the worker disabled."
  }
}

variable "deploy_api_service" {
  description = "Enable App Runner and CloudFront only after the ECR repository exists, an approved image digest is pushed, identity/DNS/TLS are ready, and release gates are accepted."
  type        = bool
  default     = false
}
