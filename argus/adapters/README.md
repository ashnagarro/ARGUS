# Infrastructure plan adapters

ARGUS normalizes each source plan into the shared `Change` model. The model records the
original `source_tool` and a portable `canonical_type`, alongside the resource address,
source resource type, actions, before and after values, replacement paths, and tags.
`argus/parse_plan.py` selects an adapter; `argus/adapters/terraform.py` handles Terraform
plan JSON. Rules inspect `Change` fields only, never raw Terraform JSON.

| Source tool / cloud | Source resource type | Canonical type | Status |
| --- | --- | --- | --- |
| Terraform / AWS | `aws_db_instance`, `aws_rds_cluster`, `aws_ebs_volume`, `aws_s3_bucket` | `data_store` | Implemented |
| Terraform / AWS | `aws_security_group`, `aws_security_group_rule`, `aws_vpc_security_group_ingress_rule` | `network_ingress` | Implemented |
| Terraform / AWS | `aws_s3_bucket_server_side_encryption_configuration` | `encryption_config` | Implemented |
| Terraform / AWS | `aws_backup_plan` | `backup_config` | Implemented |
| Terraform / AWS | `aws_db_parameter_group` | `engine_config` | Implemented |
| CloudFormation / AWS | `AWS::RDS::DBInstance` | `data_store` | Mapping design only; adapter not implemented |
| Bicep / Azure | `Microsoft.Sql/servers/databases` | `data_store` | Mapping design only; adapter not implemented |

Future adapters can translate CloudFormation change-set JSON, Bicep what-if output, or
Pulumi previews into the same `Change` objects. Each adapter should preserve the source
resource type and map it to a canonical type so shared rules can run across tools.
Unknown Terraform types retain their source type as `canonical_type` until mapped.

Azure plans need an Azure-specific rule pack and local document corpus. Adapter
normalization alone does not make AWS-specific rules or evidence applicable to Azure.
