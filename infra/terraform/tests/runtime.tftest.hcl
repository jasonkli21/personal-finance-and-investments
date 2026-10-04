mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789012" }
  }
}
mock_provider "google-beta" {}
variables {
  project_id             = "finance-contract-test"
  private_bucket         = "finance-contract-test-private"
  hosting_site           = "finance-contract-test"
  public_origin          = "https://finance-contract-test.web.app"
  auth_issuer_url        = "https://identity.example.test"
  auth_client_id         = "synthetic-client"
  auth_allowed_subject   = "synthetic-owner"
  auth_personal_scope_id = "synthetic-scope"
}
run "bootstrap" {
  command = plan
  assert {
    condition     = length(google_cloud_run_v2_service.api) == 0 && length(google_cloud_run_v2_job.worker) == 0
    error_message = "Bootstrap must not deploy an unconfigured runtime."
  }
  assert {
    condition     = google_storage_bucket.private_files.public_access_prevention == "enforced"
    error_message = "Private objects must not be publicly accessible."
  }
}
run "bounded_runtime" {
  command = plan
  variables {
    enable_runtime   = true
    api_image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    billing_account  = "000000-000000-000000"
  }
  assert {
    condition     = google_cloud_run_v2_service.api[0].template[0].scaling[0].max_instance_count == 2
    error_message = "API scaling must remain bounded."
  }
  assert {
    condition     = google_cloud_run_v2_job.worker[0].template[0].task_count == 1
    error_message = "Worker execution must remain bounded."
  }
  assert {
    condition     = google_billing_budget.project[0].budget_filter[0].projects == toset(["projects/123456789012"])
    error_message = "Budget filter must bind the target project number."
  }
}
