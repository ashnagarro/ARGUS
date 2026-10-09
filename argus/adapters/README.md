# Infrastructure plan adapters

ARGUS normalizes each source plan into the shared `Change` model. The model records the
original `source_tool` and a portable `canonical_type`, alongside the resource address,
source resource type, actions, before and after values, replacement paths, and tags.
`argus/parse_plan.py` selects an adapter; `argus/adapters/terraform.py` handles Terraform
plan JSON. Rules inspect `Change` fields only, never raw Terraform JSON.

Future adapters can translate CloudFormation change-set JSON, Bicep what-if output, or
Pulumi previews into the same `Change` objects. Each adapter should preserve the source
resource type and map it to a canonical type so shared rules can run across tools.

Azure plans need an Azure-specific rule pack and local document corpus. Adapter
normalization alone does not make AWS rules or AWS evidence applicable to Azure.
