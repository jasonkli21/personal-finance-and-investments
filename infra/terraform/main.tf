locals {
  name             = var.resource_name_prefix
  public_origin    = "https://${var.app_domain_name}"
  cluster_endpoint = "${aws_dsql_cluster.finance.identifier}.dsql.${var.aws_region}.on.aws"
  common_tags = {
    Stage     = "4"
    DataClass = "personal-financial"
  }
  app_environment = {
    APP_ENV                          = "production"
    APP_PUBLIC_ORIGIN                = local.public_origin
    AUTH_ALLOWED_SUBJECT             = var.auth_allowed_subject
    AUTH_CLIENT_ID                   = var.auth_client_id
    AUTH_COOKIE_SECURE               = "true"
    AUTH_ENABLED                     = "true"
    AUTH_ISSUER_URL                  = var.auth_issuer_url
    AUTH_PERSONAL_SCOPE_ID           = var.auth_personal_scope_id
    AURORA_DSQL_CLUSTER_ENDPOINT     = local.cluster_endpoint
    AURORA_DSQL_DB_USER              = var.app_database_role
    AURORA_DSQL_MIGRATION_DB_USER    = var.migration_database_role
    AWS_REGION                       = var.aws_region
    DATABASE_BACKEND                 = "aurora_dsql"
    DATABASE_CONNECT_TIMEOUT_SECONDS = "10"
    DATABASE_MAX_OVERFLOW            = "2"
    DATABASE_POOL_RECYCLE_SECONDS    = "600"
    DATABASE_POOL_SIZE               = "3"
    DEMO_MODE                        = "false"
    FILE_STORAGE_BACKEND             = "s3"
    JOB_WORKER_ENABLED               = "false"
    JOB_MAX_ATTEMPTS                 = "3"
    MAX_IMPORT_FILE_BYTES            = "5000000"
    MAX_IMPORT_ROWS                  = tostring(var.api_max_import_rows)
    MAX_PDF_PAGES                    = "40"
    MAX_PRIVATE_FILE_BYTES           = "20000000"
    PDF_PARSER_TIMEOUT_SECONDS       = "8"
    PERSONAL_AI_ENABLED              = "false"
    PRIVATE_S3_BUCKET                = aws_s3_bucket.private_files.bucket
    STATIC_ASSETS_BUCKET             = aws_s3_bucket.static_assets.bucket
  }
}

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_dsql_cluster" "finance" {
  deletion_protection_enabled = true
  force_destroy               = false

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(local.common_tags, {
    Name    = "${local.name}-finance"
    Purpose = "financial-database"
  })
}

resource "aws_s3_bucket" "private_files" {
  bucket        = "${var.resource_name_prefix}-private-${random_id.bucket_suffix.hex}"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(local.common_tags, {
    Purpose = "private-statements-and-encrypted-exports"
  })
}

resource "aws_s3_bucket" "static_assets" {
  bucket        = "${var.resource_name_prefix}-static-${random_id.bucket_suffix.hex}"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = merge(local.common_tags, {
    Purpose = "private-static-web-origin"
  })
}

resource "aws_s3_bucket_public_access_block" "private_files" {
  bucket                  = aws_s3_bucket.private_files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_public_access_block" "static_assets" {
  bucket                  = aws_s3_bucket.static_assets.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "private_files" {
  bucket = aws_s3_bucket.private_files.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_ownership_controls" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "private_files" {
  bucket = aws_s3_bucket.private_files.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "static_assets" {
  bucket = aws_s3_bucket.static_assets.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_policy" "private_files_transport" {
  bucket = aws_s3_bucket.private_files.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.private_files.arn,
        "${aws_s3_bucket.private_files.arn}/*"
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.private_files]
}

resource "aws_s3_bucket_policy" "static_origin" {
  count  = var.deploy_api_service ? 1 : 0
  bucket = aws_s3_bucket.static_assets.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowReadFromThisCloudFrontDistribution"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.static_assets.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.app[0].arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.static_assets.arn,
          "${aws_s3_bucket.static_assets.arn}/*"
        ]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.static_assets]
}

resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = merge(local.common_tags, {
    Purpose = "api-container-images"
  })
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Retain recent immutable release images for bounded rollback"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_budgets_budget" "account_monthly_cost" {
  provider = aws.billing
  count    = var.monthly_cost_budget_usd == null ? 0 : 1

  name         = "${local.name}-account-monthly-cost"
  account_id   = var.aws_account_id
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_cost_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  tags         = merge(local.common_tags, { Owner = var.resource_owner_tag, Purpose = "whole-account-cost-alert" })

  cost_types {
    # Model post-credit exposure because AWS Free Tier credits can expire.
    include_credit = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.cost_alert_email_addresses
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.cost_alert_email_addresses
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.cost_alert_email_addresses
  }

  lifecycle {
    precondition {
      condition     = length(var.cost_alert_email_addresses) > 0
      error_message = "An explicit recipient is required before creating an AWS cost budget."
    }
  }
}

data "aws_iam_policy_document" "apprunner_ecr_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["build.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_ecr_access" {
  name               = "${local.name}-apprunner-ecr"
  assume_role_policy = data.aws_iam_policy_document.apprunner_ecr_trust.json
  tags               = merge(local.common_tags, { Purpose = "apprunner-image-pull" })
}

resource "aws_iam_role_policy" "apprunner_ecr_access" {
  name = "pull-api-image"
  role = aws_iam_role.apprunner_ecr_access.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "TokenRequiredByECR"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid    = "PullOnlyThisRepository"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = aws_ecr_repository.api.arn
      }
    ]
  })
}

data "aws_iam_policy_document" "apprunner_instance_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["tasks.apprunner.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apprunner_instance" {
  name               = "${local.name}-apprunner-runtime"
  assume_role_policy = data.aws_iam_policy_document.apprunner_instance_trust.json
  tags               = merge(local.common_tags, { Purpose = "api-runtime" })
}

resource "aws_iam_role_policy" "apprunner_instance" {
  count = var.deploy_api_service ? 1 : 0
  name  = "private-storage-dsql-and-auth-secrets"
  role  = aws_iam_role.apprunner_instance.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PrivateFileBucketList"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.private_files.arn
      },
      {
        Sid      = "PrivateFileObjectsOnly"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.private_files.arn}/*"
      },
      {
        Sid      = "ConnectAsApplicationRole"
        Effect   = "Allow"
        Action   = "dsql:DbConnect"
        Resource = aws_dsql_cluster.finance.arn
      },
      {
        Sid      = "ReadOnlyConfiguredAuthSecrets"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = [var.auth_client_secret_arn, var.auth_session_signing_key_secret_arn]
      }
    ]
  })
}

data "aws_iam_policy_document" "migration_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.migration_trusted_principal_arn]
    }
  }
}

resource "aws_iam_role" "dsql_migration" {
  name                 = "${local.name}-dsql-migration"
  assume_role_policy   = data.aws_iam_policy_document.migration_trust.json
  max_session_duration = 3600
  tags                 = merge(local.common_tags, { Purpose = "operator-schema-migration" })
}

resource "aws_iam_role_policy" "dsql_migration" {
  name = "admin-connect-only-to-finance-cluster"
  role = aws_iam_role.dsql_migration.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "dsql:DbConnectAdmin"
      Resource = aws_dsql_cluster.finance.arn
    }]
  })
}

resource "aws_apprunner_auto_scaling_configuration_version" "api" {
  count                           = var.deploy_api_service ? 1 : 0
  auto_scaling_configuration_name = "${local.name}-api-bounded"
  max_concurrency                 = var.api_max_concurrency
  max_size                        = 1
  min_size                        = 1
  tags                            = merge(local.common_tags, { Purpose = "bounded-api-capacity" })
}

resource "aws_apprunner_service" "api" {
  count                          = var.deploy_api_service ? 1 : 0
  service_name                   = "${local.name}-api"
  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.api[0].arn

  lifecycle {
    precondition {
      condition     = var.apprunner_existing_customer_confirmed
      error_message = "Confirm target-account eligibility: AWS stopped accepting new App Runner customers on 2026-03-31."
    }
  }

  source_configuration {
    auto_deployments_enabled = false
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr_access.arn
    }
    image_repository {
      image_identifier      = "${aws_ecr_repository.api.repository_url}@${var.api_image_digest}"
      image_repository_type = "ECR"
      image_configuration {
        port = "8000"
        runtime_environment_variables = merge(local.app_environment, {
          AUTH_SESSION_TTL_SECONDS = "28800"
        })
        runtime_environment_secrets = {
          AUTH_CLIENT_SECRET       = var.auth_client_secret_arn
          AUTH_SESSION_SIGNING_KEY = var.auth_session_signing_key_secret_arn
        }
      }
    }
  }

  instance_configuration {
    cpu               = var.api_cpu
    memory            = var.api_memory
    instance_role_arn = aws_iam_role.apprunner_instance.arn
  }

  health_check_configuration {
    protocol            = "HTTP"
    path                = "/health/ready"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 1
    unhealthy_threshold = 3
  }

  network_configuration {
    egress_configuration {
      egress_type = "DEFAULT"
    }
    ingress_configuration {
      is_publicly_accessible = true
    }
  }

  tags = merge(local.common_tags, { Purpose = "authenticated-finance-api" })
}

resource "aws_cloudfront_origin_access_control" "static_assets" {
  count                             = var.deploy_api_service ? 1 : 0
  name                              = "${local.name}-static-oac"
  description                       = "Read only access to the private static asset origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_function" "api_prefix" {
  count   = var.deploy_api_service ? 1 : 0
  name    = "${local.name}-strip-api-prefix"
  runtime = "cloudfront-js-2.0"
  comment = "Strip the public /api prefix before forwarding to FastAPI."
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri === "/api") {
        request.uri = "/";
      } else if (request.uri.indexOf("/api/") === 0) {
        request.uri = request.uri.substring(4);
      }
      return request;
    }
  JS
}

resource "aws_cloudfront_function" "spa_routes" {
  count   = var.deploy_api_service ? 1 : 0
  name    = "${local.name}-spa-route-fallback"
  runtime = "cloudfront-js-2.0"
  comment = "Route extensionless client paths to the SPA without rewriting API errors."
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri !== "/" && request.uri.indexOf(".") === -1) {
        request.uri = "/index.html";
      }
      return request;
    }
  JS
}

resource "aws_cloudfront_cache_policy" "api_no_cache" {
  count       = var.deploy_api_service ? 1 : 0
  name        = "${local.name}-api-no-cache"
  comment     = "Authenticated API responses must never be cached."
  min_ttl     = 0
  default_ttl = 0
  max_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "all"
    }
    headers_config {
      header_behavior = "whitelist"
      headers {
        items = ["Authorization", "Content-Type", "Origin", "Sec-Fetch-Site", "X-Requested-With"]
      }
    }
    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

resource "aws_cloudfront_cache_policy" "static_assets" {
  count       = var.deploy_api_service ? 1 : 0
  name        = "${local.name}-static-assets"
  comment     = "Short bounded cache for versioned Vite assets and the SPA shell."
  min_ttl     = 0
  default_ttl = 3600
  max_ttl     = 86400

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

resource "aws_cloudfront_response_headers_policy" "security" {
  count   = var.deploy_api_service ? 1 : 0
  name    = "${local.name}-security-headers"
  comment = "Baseline browser security headers for finance pages and API responses."

  security_headers_config {
    content_type_options { override = true }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "same-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = true
    }
  }
}

resource "aws_cloudfront_distribution" "app" {
  count           = var.deploy_api_service ? 1 : 0
  enabled         = true
  comment         = "Personal Finance private SPA and authenticated API edge"
  aliases         = [var.app_domain_name]
  is_ipv6_enabled = true
  price_class     = "PriceClass_100"

  origin {
    domain_name              = aws_s3_bucket.static_assets.bucket_regional_domain_name
    origin_id                = "private-static-assets"
    origin_access_control_id = aws_cloudfront_origin_access_control.static_assets[0].id
  }

  origin {
    domain_name = aws_apprunner_service.api[0].service_url
    origin_id   = "apprunner-api"
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id           = "private-static-assets"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = aws_cloudfront_cache_policy.static_assets[0].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security[0].id
    compress                   = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_routes[0].arn
    }
  }

  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = "apprunner-api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.api_no_cache[0].id
    # AWS managed AllViewerExceptHostHeader: pass import/idempotency/auth/CSRF
    # and future API contract headers while preserving the origin Host header.
    origin_request_policy_id   = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security[0].id
    compress                   = true
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.api_prefix[0].arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.cloudfront_acm_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = merge(local.common_tags, { Purpose = "https-web-entrypoint" })
}

output "cloudfront_distribution_id" {
  description = "Distribution ID used for a reviewed static asset invalidation."
  value       = try(aws_cloudfront_distribution.app[0].id, null)
}

output "cloudfront_domain_name" {
  description = "CloudFront hostname; externally managed DNS must alias app_domain_name here."
  value       = try(aws_cloudfront_distribution.app[0].domain_name, null)
}

output "app_public_origin" {
  description = "Exact origin registered in the OIDC provider and production app settings."
  value       = local.public_origin
}

output "app_runner_direct_origin" {
  description = "Public App Runner endpoint; callers can bypass CloudFront/WAF, so API authorization remains mandatory at this origin."
  value       = try("https://${aws_apprunner_service.api[0].service_url}", null)
}

output "api_ecr_repository_url" {
  description = "ECR repository to which an approved immutable API image must be pushed."
  value       = aws_ecr_repository.api.repository_url
}

output "api_service_arn" {
  description = "App Runner service ARN for release and bounded log-retention operations."
  value       = try(aws_apprunner_service.api[0].arn, null)
}

output "dsql_cluster_arn" {
  description = "Single-region DSQL cluster ARN."
  value       = aws_dsql_cluster.finance.arn
}

output "dsql_cluster_endpoint" {
  description = "Official clusterid.dsql.region.on.aws endpoint format; use with IAM token-on-connect and TLS verify-full."
  value       = local.cluster_endpoint
}

output "dsql_migration_role_arn" {
  description = "Assume only for explicitly approved schema migration operations."
  value       = aws_iam_role.dsql_migration.arn
}

output "private_file_bucket" {
  description = "Private statements and encrypted portable exports; not a web origin."
  value       = aws_s3_bucket.private_files.bucket
}

output "static_assets_bucket" {
  description = "Private CloudFront-only Vite asset origin."
  value       = aws_s3_bucket.static_assets.bucket
}

output "account_monthly_cost_budget_name" {
  description = "Optional whole-account AWS Budgets alert; null when no operator-selected amount was supplied."
  value       = try(aws_budgets_budget.account_monthly_cost[0].name, null)
}

output "account_monthly_cost_budget_arn" {
  description = "Optional account cost-alert resource ARN; this is not an account spending cap."
  value       = try(aws_budgets_budget.account_monthly_cost[0].arn, null)
}
