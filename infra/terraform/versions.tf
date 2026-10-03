terraform {
  required_version = "= 1.16.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.67.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.7.2"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Application = "personal-finance"
      Environment = "production"
      ManagedBy   = "terraform"
      Owner       = var.resource_owner_tag
    }
  }
}

# AWS Budgets is an account-level billing control plane. Keep its supported
# endpoint in us-east-1 independent of the operator-selected data Region.
provider "aws" {
  alias  = "billing"
  region = "us-east-1"
}

provider "random" {}
