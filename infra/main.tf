# Counterplay's AWS side. The site itself stays on the Hetzner box; this is
# only what watches it and what keeps a live copy of its database.
#
#   monitor.tf   uptime and worker check, Lambda every 5 minutes, email alarm
#   backup.tf    the S3 bucket Litestream replicates the database into
#
# Run from this folder (infra/README.md is the whole procedure):
#   terraform init
#   terraform apply
#
# State is a local file, gitignored: it names the account and the bucket.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

# Ohio, because it is the only region the account allows: it was made in
# AWS's "new experience", which puts it under an AWS-managed organization
# whose policy denies every region but the project's. Frankfurt, next to the
# box, was the first choice and is refused outright (2026-10-16).
#
# Profile counterplay-tf is the browser sign-in (`aws login --profile
# counterplay`) handed to Terraform through credential_process in
# ~/.aws/config. No access key is stored anywhere; the sign-in lasts 12
# hours and renews for 90 days.
provider "aws" {
  region  = "us-east-2"
  profile = "counterplay-tf"
  default_tags {
    tags = { project = "counterplay" }
  }
}

variable "alert_email" {
  description = "Where outage and billing emails go."
  type        = string
}

variable "backup_bucket" {
  description = "S3 bucket for the Litestream replica. Globally unique, e.g. counterplay-db-replica-7f3k."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Email when AWS spend reaches this. It alerts; it does not stop anything."
  type        = string
  default     = "5"
}

# AWS has no spending cap. This is the next best thing: an email when the
# month's real spend, or the forecast for it, passes the budget.
resource "aws_budgets_budget" "monthly" {
  name         = "counterplay-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
