terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region                      = "us-east-1"
  access_key                  = "FAKE_ACCESS_KEY_FOR_LOCAL_PLAN"
  secret_key                  = "FAKE_SECRET_KEY_FOR_LOCAL_PLAN"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}

resource "aws_security_group" "sqlserver_demo" {
  name        = "argus-sqlserver-demo"
  description = "Synthetic SQL Server demo security group"

  tags = {
    env   = "demo"
    owner = "synthetic-team"
  }
}

resource "aws_security_group_rule" "public_sqlserver" {
  type              = "ingress"
  security_group_id = aws_security_group.sqlserver_demo.id
  from_port         = 1433
  to_port           = 1433
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Synthetic unsafe example for ARGUS"
}

resource "aws_db_instance" "sqlserver_demo" {
  identifier             = "argus-sqlserver-demo"
  allocated_storage      = 20
  engine                 = "sqlserver-ex"
  instance_class         = "db.t3.small"
  username               = "synthetic_admin"
  password               = "FAKE_PASSWORD_FOR_LOCAL_PLAN_ONLY"
  vpc_security_group_ids = [aws_security_group.sqlserver_demo.id]
  storage_encrypted      = true
  deletion_protection    = true
  skip_final_snapshot    = false
  final_snapshot_identifier = "argus-sqlserver-demo-final"

  tags = {
    env                 = "demo"
    data_classification = "synthetic"
    owner               = "synthetic-team"
  }
}
