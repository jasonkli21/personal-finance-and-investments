variable "project_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Supply an existing dedicated GCP project ID."
  }
}
variable "region" {
  type    = string
  default = "us-central1"
  validation {
    condition     = contains(["us-central1", "us-east1", "us-west1", "europe-west1", "asia-east1"], var.region)
    error_message = "Use a documented Firebase Hosting Cloud Run rewrite region."
  }
}
variable "name" {
  type    = string
  default = "personal-finance"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "name must be 3–25 lowercase resource-name characters."
  }
}
variable "private_bucket" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.private_bucket))
    error_message = "Supply a globally unique private bucket name."
  }
}
variable "hosting_site" {
  type = string
}
variable "public_origin" {
  type = string
  validation {
    condition     = can(regex("^https://[a-z0-9.-]+$", var.public_origin))
    error_message = "Use the exact HTTPS Firebase/custom origin, without path."
  }
}
variable "auth_issuer_url" {
  type = string
  validation {
    condition     = can(regex("^https://[^?#]+$", var.auth_issuer_url))
    error_message = "Use the exact HTTPS OIDC issuer."
  }
}
variable "auth_client_id" {
  type = string
}
variable "auth_allowed_subject" {
  type = string
}
variable "auth_personal_scope_id" {
  type = string
}
variable "enable_runtime" {
  description = "Bootstrap registry/bucket/secret containers first; deploy only after publishing secrets and an immutable image."
  type        = bool
  default     = false
}
variable "api_image_digest" {
  type     = string
  default  = null
  nullable = true
  validation {
    condition     = var.api_image_digest == null ? true : can(regex("^sha256:[0-9a-f]{64}$", var.api_image_digest))
    error_message = "Use an immutable OCI sha256 digest."
  }
}
variable "secret_versions" {
  description = "Pinned pre-existing Secret Manager version numbers; values never enter Terraform."
  type        = map(string)
  default     = { database = "1", oidc_client = "1", session_signing = "1" }
  validation {
    condition     = toset(keys(var.secret_versions)) == toset(["database", "oidc_client", "session_signing"]) && alltrue([for v in values(var.secret_versions) : can(regex("^[1-9][0-9]*$", v))])
    error_message = "Supply numeric versions for the three required secrets."
  }
}
variable "billing_account" {
  description = "Optional billing account ID for an alert-only budget. Neon billing is separate."
  type        = string
  default     = null
}
variable "monthly_budget_usd" {
  type    = number
  default = 20
  validation {
    condition     = var.monthly_budget_usd >= 1 && var.monthly_budget_usd <= 100 && floor(var.monthly_budget_usd) == var.monthly_budget_usd
    error_message = "Set an explicitly reviewed personal-project budget."
  }
}
