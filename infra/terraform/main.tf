locals {
  services = toset(["run.googleapis.com", "artifactregistry.googleapis.com", "secretmanager.googleapis.com", "storage.googleapis.com", "firebase.googleapis.com", "firebasehosting.googleapis.com", "cloudbilling.googleapis.com", "billingbudgets.googleapis.com", "logging.googleapis.com"])
  secrets  = { database = "DATABASE_URL", oidc_client = "AUTH_CLIENT_SECRET", session_signing = "AUTH_SESSION_SIGNING_KEY" }
  image    = "${var.region}-docker.pkg.dev/${var.project_id}/${var.name}/api@${var.api_image_digest == null ? "unset" : var.api_image_digest}"
  settings = {
    APP_ENV                = "production"
    APP_PUBLIC_ORIGIN      = var.public_origin
    AUTH_ENABLED           = "true"
    AUTH_COOKIE_SECURE     = "true"
    AUTH_ISSUER_URL        = var.auth_issuer_url
    AUTH_CLIENT_ID         = var.auth_client_id
    AUTH_ALLOWED_SUBJECT   = var.auth_allowed_subject
    AUTH_PERSONAL_SCOPE_ID = var.auth_personal_scope_id
    FILE_STORAGE_BACKEND   = "gcs"
    PRIVATE_GCS_BUCKET     = var.private_bucket
    GCP_PROJECT            = var.project_id
    PERSONAL_AI_ENABLED    = "false"
    DEMO_MODE              = "false"
    JOB_WORKER_ENABLED     = "false"
    DATABASE_POOL_SIZE     = "5"
    DATABASE_MAX_OVERFLOW  = "0"
  }
}
resource "google_project_service" "required" {
  for_each           = local.services
  service            = each.key
  disable_on_destroy = false
}
# This dedicated project's default log bucket is managed without deleting it.
resource "google_logging_project_bucket_config" "default" {
  project        = var.project_id
  location       = "global"
  bucket_id      = "_Default"
  retention_days = 30
  depends_on     = [google_project_service.required]
}
# Managed request logs include URLs. Retain app route-template/request-ID logs
# instead; custom/organization sinks must be reviewed independently before use.
resource "google_logging_project_exclusion" "request_urls" {
  project     = var.project_id
  name        = "${var.name}-request-urls"
  description = "Exclude query-bearing Cloud Run request logs from the default sink"
  filter      = "resource.type=\"cloud_run_revision\" AND logName=\"projects/${var.project_id}/logs/run.googleapis.com%2Frequests\""
  depends_on  = [google_project_service.required]
}
resource "google_artifact_registry_repository" "api" {
  location      = var.region
  repository_id = var.name
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}
resource "google_storage_bucket" "private_files" {
  name                        = var.private_bucket
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  versioning { enabled = true }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}
resource "google_service_account" "runtime" {
  for_each   = toset(["api", "worker"])
  account_id = "${var.name}-${each.key}"
}
resource "google_storage_bucket_iam_member" "read" {
  for_each = google_service_account.runtime
  bucket   = google_storage_bucket.private_files.name
  role     = "roles/storage.objectViewer"
  member   = "serviceAccount:${each.value.email}"
}
resource "google_storage_bucket_iam_member" "create" {
  for_each = google_service_account.runtime
  bucket   = google_storage_bucket.private_files.name
  role     = "roles/storage.objectCreator"
  member   = "serviceAccount:${each.value.email}"
}
resource "google_secret_manager_secret" "runtime" {
  for_each  = local.secrets
  secret_id = "${var.name}-${each.key}"
  replication {
    auto {}
  }
  lifecycle { prevent_destroy = true }
  depends_on = [google_project_service.required]
}
resource "google_secret_manager_secret_iam_member" "runtime" {
  for_each  = { for pair in setproduct(keys(local.secrets), keys(google_service_account.runtime)) : "${pair[0]}-${pair[1]}" => pair }
  secret_id = google_secret_manager_secret.runtime[each.value[0]].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime[each.value[1]].email}"
}
resource "google_cloud_run_v2_job" "worker" {
  count               = var.enable_runtime ? 1 : 0
  name                = "${var.name}-worker"
  location            = var.region
  deletion_protection = true
  template {
    task_count  = 1
    parallelism = 1
    template {
      service_account = google_service_account.runtime["worker"].email
      timeout         = "300s"
      max_retries     = 1
      containers {
        image   = local.image
        command = ["python", "-m", "app.jobs.once"]
        resources { limits = { cpu = "1", memory = "512Mi" } }
        dynamic "env" {
          for_each = local.settings
          content {
            name  = env.key
            value = env.value
          }
        }
        dynamic "env" {
          for_each = local.secrets
          content {
            name = env.value
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.runtime[env.key].secret_id
                version = var.secret_versions[env.key]
              }
            }
          }
        }
      }
    }
  }
  lifecycle {
    precondition {
      condition     = var.api_image_digest != null
      error_message = "Publish the source-bound image before enabling runtime."
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.runtime, google_storage_bucket_iam_member.read, google_storage_bucket_iam_member.create]
}
resource "google_cloud_run_v2_service" "api" {
  count               = var.enable_runtime ? 1 : 0
  name                = var.name
  location            = var.region
  deletion_protection = true
  # Firebase requires internet ingress and an invokable service. All finance
  # routes enforce OIDC even at the direct service URL; no private object URLs.
  ingress = "INGRESS_TRAFFIC_ALL"
  template {
    service_account                  = google_service_account.runtime["api"].email
    max_instance_request_concurrency = 8
    timeout                          = "60s"
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = local.image
      ports { container_port = 8000 }
      resources {
        limits   = { cpu = "1", memory = "512Mi" }
        cpu_idle = true
      }
      startup_probe {
        http_get { path = "/health" }
      }
      dynamic "env" {
        for_each = merge(local.settings, { CLOUD_RUN_JOB = google_cloud_run_v2_job.worker[0].id })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.secrets
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.runtime[env.key].secret_id
              version = var.secret_versions[env.key]
            }
          }
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.runtime, google_storage_bucket_iam_member.read, google_storage_bucket_iam_member.create]
}
resource "google_cloud_run_v2_service_iam_member" "hosting" {
  count    = var.enable_runtime ? 1 : 0
  name     = google_cloud_run_v2_service.api[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
resource "google_cloud_run_v2_job_iam_member" "api_execute" {
  count    = var.enable_runtime ? 1 : 0
  name     = google_cloud_run_v2_job.worker[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime["api"].email}"
}
resource "google_firebase_project" "finance" {
  provider   = google-beta
  project    = var.project_id
  depends_on = [google_project_service.required]
}
resource "google_firebase_hosting_site" "spa" {
  provider   = google-beta
  project    = var.project_id
  site_id    = var.hosting_site
  depends_on = [google_firebase_project.finance]
}
data "google_project" "finance" {
  project_id = var.project_id
}

resource "google_billing_budget" "project" {
  count           = var.billing_account == null ? 0 : 1
  billing_account = var.billing_account
  display_name    = "${var.name} monthly alerts (not a spending cap)"
  budget_filter { projects = ["projects/${data.google_project.finance.number}"] }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules { threshold_percent = 1.0 }
}
output "image_repository" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${var.name}/api" }
output "api_url" { value = var.enable_runtime ? google_cloud_run_v2_service.api[0].uri : null }
output "firebase_config" {
  value = {
    hosting = {
      site   = google_firebase_hosting_site.spa.site_id
      public = "../../apps/web/dist"
      ignore = ["firebase.json", "**/.*", "**/node_modules/**"]
      rewrites = [
        { source = "/api/**", run = { serviceId = var.name, region = var.region, pinTag = true } },
        { source = "**", destination = "/index.html" }
      ]
      headers = [{ source = "**", headers = [{ key = "X-Content-Type-Options", value = "nosniff" }, { key = "X-Frame-Options", value = "DENY" }, { key = "Referrer-Policy", value = "no-referrer" }, { key = "Strict-Transport-Security", value = "max-age=31536000" }] }]
    }
  }
}
