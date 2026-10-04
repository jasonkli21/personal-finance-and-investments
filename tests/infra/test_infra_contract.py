"""Offline IaC guardrails; actual provider schema validation runs separately."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "infra/terraform/main.tf").read_text()
VARIABLES = (ROOT / "infra/terraform/variables.tf").read_text()


class InfrastructureContract(unittest.TestCase):
    def test_private_storage_and_least_privilege(self) -> None:
        self.assertIn('public_access_prevention    = "enforced"', MAIN)
        self.assertIn("uniform_bucket_level_access = true", MAIN)
        self.assertIn("force_destroy               = false", MAIN)
        self.assertIn("roles/storage.objectCreator", MAIN)
        self.assertIn("roles/storage.objectViewer", MAIN)
        self.assertNotIn("roles/storage.admin", MAIN)
        self.assertNotIn("roles/editor", MAIN)
        self.assertNotIn("google_service_account_key", MAIN)
        self.assertNotIn("google_secret_manager_secret_version", MAIN)

    def test_bounded_runtime_and_immutable_image(self) -> None:
        self.assertRegex(MAIN, r"max_instance_count\s*=\s*2")
        self.assertRegex(MAIN, r"max_instance_request_concurrency\s*=\s*8")
        self.assertRegex(MAIN, r"task_count\s*=\s*1")
        self.assertRegex(MAIN, r"parallelism\s*=\s*1")
        self.assertIn("app.jobs.once", MAIN)
        self.assertIn("api@${var.api_image_digest", MAIN)
        self.assertIn("sha256:", VARIABLES)
        self.assertIn("var.enable_runtime ? 1 : 0", MAIN)
        self.assertNotIn("latest", MAIN)

    def test_identity_secrets_and_auth_gate(self) -> None:
        self.assertIn("roles/secretmanager.secretAccessor", MAIN)
        self.assertIn("roles/run.invoker", MAIN)
        self.assertIn("AUTH_ENABLED", MAIN)
        self.assertIn("AUTH_COOKIE_SECURE", MAIN)
        self.assertIn("PERSONAL_AI_ENABLED", MAIN)
        self.assertIn("DATABASE_MAX_OVERFLOW", MAIN)
        self.assertIn("secret_key_ref", MAIN)
        self.assertIn("var.secret_versions", MAIN)
        public_blocks = re.findall(
            r'resource "([^"]+)"[^\n]*\{.*?member\s*=\s*"allUsers"', MAIN, re.S
        )
        self.assertTrue(public_blocks)
        # The only public principal is the Cloud Run API. Its domain routes
        # remain protected by OIDC; buckets and jobs receive no public grant.
        self.assertEqual(MAIN.count('"allUsers"'), 1)

    def test_same_origin_firebase_rewrites_precede_spa(self) -> None:
        self.assertLess(MAIN.index('source = "/api/**"'), MAIN.index('source = "**"'))
        self.assertIn("pinTag = true", MAIN)
        self.assertIn("../../apps/web/dist", MAIN)
        self.assertIn("google_firebase_hosting_site", MAIN)
        self.assertIn("Strict-Transport-Security", MAIN)
        self.assertIn("max-age=31536000", MAIN)

    def test_private_log_retention(self) -> None:
        self.assertIn("google_logging_project_bucket_config", MAIN)
        self.assertRegex(MAIN, r"retention_days\s*=\s*30")
        self.assertIn("google_logging_project_exclusion", MAIN)
        self.assertIn("run.googleapis.com%2Frequests", MAIN)

    def test_cost_alerts_are_not_caps(self) -> None:
        self.assertIn("google_billing_budget", MAIN)
        self.assertIn("not a spending cap", MAIN)
        self.assertIn("var.billing_account == null ? 0 : 1", MAIN)
        self.assertIn("prevent_destroy = true", MAIN)


if __name__ == "__main__":
    unittest.main()
