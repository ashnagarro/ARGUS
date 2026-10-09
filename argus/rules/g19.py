"""G19: S3 bucket versioning is suspended."""

from collections.abc import Sequence
from typing import Any

from argus.models import Change, RuleFinding
from argus.rules import Rule


def _configuration(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return {}


def _suspended(resource_type: str, state: dict[str, Any] | None) -> bool:
    if not state:
        return False
    if resource_type == "aws_s3_bucket_versioning":
        return _configuration(state.get("versioning_configuration")).get("status") == "Suspended"
    if resource_type == "aws_s3_bucket":
        return _configuration(state.get("versioning")).get("enabled") is False
    return False


class G19S3VersioningSuspended(Rule):
    id = "G19"
    name = "object-versioning-suspended"
    title = "Object versioning suspended"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Suspended versioning stops creating new object versions for recovery."
    how_to_fix = "Set versioning_configuration.status = \"Enabled\" for the S3 bucket."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type not in {"aws_s3_bucket_versioning", "aws_s3_bucket"}:
            return []
        if _suspended(change.resource_type, change.after):
            return [self.finding(change, "S3 bucket versioning will be suspended.")]
        if (change.resource_type == "aws_s3_bucket_versioning"
                and "delete" in change.actions and change.after is None
                and _suspended(change.resource_type, change.before) is False):
            # Deleting the versioning resource may suspend versioning, but can also
            # remove only Terraform ownership for an unversioned bucket. Only flag
            # deletion when the plan confirms versioning was enabled beforehand.
            before = change.before or {}
            if _configuration(before.get("versioning_configuration")).get("status") == "Enabled":
                return [self.finding(change, "Deleting enabled S3 bucket versioning may suspend it.")]
        return []
