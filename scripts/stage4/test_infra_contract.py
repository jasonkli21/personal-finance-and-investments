"""Text-level release guardrails for the reviewed Terraform topology.

These checks complement `terraform fmt` and `terraform validate`; they do not
parse HCL or establish that any AWS policy has been applied.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = ROOT / "infra" / "terraform"
MAIN = (TERRAFORM / "main.tf").read_text()
VARIABLES = (TERRAFORM / "variables.tf").read_text()
README = (TERRAFORM / "README.md").read_text()


class TerraformContractTests(unittest.TestCase):
    def test_data_plane_is_single_region_and_private(self) -> None:
        self.assertEqual(MAIN.count('resource "aws_dsql_cluster"'), 1)
        self.assertNotIn("multi_region_properties", MAIN)
        self.assertIn('resource "aws_s3_bucket" "private_files"', MAIN)
        self.assertIn('resource "aws_s3_bucket" "static_assets"', MAIN)
        self.assertEqual(MAIN.count('resource "aws_s3_bucket_public_access_block"'), 2)
        for name in (
            "private_files",
            "static_assets",
        ):
            block = MAIN.split(
                f'resource "aws_s3_bucket_public_access_block" "{name}"', 1
            )[1].split("\n}", 1)[0]
            for setting in (
                "block_public_acls       = true",
                "block_public_policy     = true",
                "ignore_public_acls      = true",
                "restrict_public_buckets = true",
            ):
                self.assertIn(setting, block)
        self.assertIn('sse_algorithm = "AES256"', MAIN)
        self.assertIn('"aws:SecureTransport" = "false"', MAIN)

    def test_runtime_and_migration_authority_are_separate(self) -> None:
        runtime = MAIN.split('resource "aws_iam_role_policy" "apprunner_instance"', 1)[
            1
        ].split('\nresource "', 1)[0]
        migration = MAIN.split('resource "aws_iam_role_policy" "dsql_migration"', 1)[
            1
        ].split('\nresource "', 1)[0]
        self.assertIn('Action   = "dsql:DbConnect"', runtime)
        self.assertNotIn("DbConnectAdmin", runtime)
        self.assertIn('Action   = "dsql:DbConnectAdmin"', migration)
        self.assertIn("aws_dsql_cluster.finance.arn", migration)
        self.assertIn("var.migration_trusted_principal_arn", MAIN)
        self.assertEqual(MAIN.count('Resource = "*"'), 1)
        token_policy = MAIN.split('Sid      = "TokenRequiredByECR"', 1)[1].split(
            "      },", 1
        )[0]
        self.assertIn('Action   = "ecr:GetAuthorizationToken"', token_policy)
        self.assertIn('Resource = "*"', token_policy)
        self.assertNotIn('Action   = "*"', MAIN)

    def test_cloudfront_does_not_expose_or_cache_financial_api(self) -> None:
        self.assertIn(
            "origin_access_control_id = "
            "aws_cloudfront_origin_access_control.static_assets[0].id",
            MAIN,
        )
        self.assertRegex(MAIN, r'path_pattern\s+=\s+"/api/\*"')
        self.assertIn('origin_protocol_policy = "https-only"', MAIN)
        api_cache = MAIN.split(
            'resource "aws_cloudfront_cache_policy" "api_no_cache"', 1
        )[1].split('\nresource "', 1)[0]
        for ttl in ("min_ttl     = 0", "default_ttl = 0", "max_ttl     = 0"):
            self.assertIn(ttl, api_cache)
        self.assertIn("function_arn = aws_cloudfront_function.spa_routes[0].arn", MAIN)
        self.assertIn("function_arn = aws_cloudfront_function.api_prefix[0].arn", MAIN)
        self.assertIn(
            "App Runner exposes a direct public service URL", " ".join(README.split())
        )
        self.assertIn("callers may bypass the edge", " ".join(README.split()))

    def test_release_prerequisites_fail_closed(self) -> None:
        self.assertIn('version = "= 6.67.0"', (TERRAFORM / "versions.tf").read_text())
        self.assertIn('version = "= 3.7.2"', (TERRAFORM / "versions.tf").read_text())
        self.assertIn(
            'image_identifier      = "${aws_ecr_repository.api.repository_url}'
            '@${var.api_image_digest}"',
            MAIN,
        )
        self.assertIn("auto_deployments_enabled = false", MAIN)
        self.assertIn("prevent_destroy = true", MAIN)
        self.assertIn("var.job_worker_enabled == false", VARIABLES)
        self.assertIn(
            "default     = false",
            VARIABLES.split('variable "deploy_api_service"', 1)[1],
        )
        self.assertIn('variable "apprunner_existing_customer_confirmed"', VARIABLES)
        self.assertIn(
            "default     = false",
            VARIABLES.split('variable "apprunner_existing_customer_confirmed"', 1)[1],
        )
        self.assertIn("condition     = var.apprunner_existing_customer_confirmed", MAIN)
        self.assertIn(
            "AWS stopped accepting new App Runner customers on 2026-03-31", MAIN
        )
        self.assertIn("deploy_api_service ? 1 : 0", MAIN)
        dockerfile = (ROOT / "services" / "api" / "Dockerfile").read_text()
        self.assertIn("COPY alembic ./alembic", dockerfile)
        self.assertIn("USER 10001:10001", dockerfile)

    def test_cost_controls_are_optional_and_workload_bounds_are_injected(self) -> None:
        budget = MAIN.split('resource "aws_budgets_budget" "account_monthly_cost"', 1)[
            1
        ].split('\nresource "', 1)[0]
        self.assertIn("provider = aws.billing", budget)
        self.assertIn("count    = var.monthly_cost_budget_usd == null ? 0 : 1", budget)
        self.assertIn('notification_type          = "ACTUAL"', budget)
        self.assertIn('notification_type          = "FORECASTED"', budget)
        self.assertIn("threshold                  = 50", budget)
        self.assertIn("threshold                  = 80", budget)
        self.assertIn("threshold                  = 100", budget)
        self.assertIn("include_credit = false", budget)
        self.assertIn("length(var.cost_alert_email_addresses) > 0", budget)
        self.assertIn('JOB_WORKER_ENABLED               = "false"', MAIN)
        self.assertIn('PERSONAL_AI_ENABLED              = "false"', MAIN)
        self.assertIn(
            "MAX_IMPORT_ROWS                  = tostring(var.api_max_import_rows)", MAIN
        )
        self.assertIn('MAX_IMPORT_FILE_BYTES            = "5000000"', MAIN)
        self.assertIn('MAX_PRIVATE_FILE_BYTES           = "20000000"', MAIN)
        self.assertIn('MAX_PDF_PAGES                    = "40"', MAIN)
        self.assertIn('PDF_PARSER_TIMEOUT_SECONDS       = "8"', MAIN)
        self.assertIn(
            "default     = 1000",
            VARIABLES.split('variable "api_max_import_rows"', 1)[1],
        )
        self.assertIn(
            "var.api_max_import_rows >= 502 && var.api_max_import_rows <= 1000",
            VARIABLES,
        )
        self.assertIn(
            "default     = null",
            VARIABLES.split('variable "monthly_cost_budget_usd"', 1)[1],
        )
        self.assertIn("countNumber = 20", MAIN)
        self.assertIn("AWS Budgets", README)


if __name__ == "__main__":
    unittest.main()
