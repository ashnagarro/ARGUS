terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 4.67"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "fake"
  secret_key                  = "fake"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true
}

resource "aws_db_instance" "orders" {
  identifier          = "synthetic-orders-db"
  allocated_storage   = 20
  engine              = "postgres"
  engine_version      = "14.11"
  instance_class      = "db.t3.micro"
  username            = "synthetic-user"
  password            = "synthetic-password"
  name                = "orders"
  skip_final_snapshot = true
  publicly_accessible = false
}

resource "aws_s3_bucket" "logs" {
  bucket = "synthetic-upgrade-logs-example"
}
