"""G03: S3 bucket policies granting access to every principal."""

import json
from typing import Mapping, Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


def _has_wildcard(value: object) -> bool:
    if value == "*":
        return True
    if isinstance(value, Mapping):
        return any(_has_wildcard(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_wildcard(item) for item in value)
    return False


class PublicS3BucketPolicy(Rule):
    id = "G03"
    name = "object-storage-policy-allows-public-access"
    title = "Storage policy allows public access"
    applies_to = ("terraform/aws",)
    severity = "critical"
    why_it_matters = "An Allow statement for every principal can expose bucket data publicly."
    how_to_fix = "Replace the wildcard Principal with the specific identities that need access."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_s3_bucket_policy" or change.after is None:
            return []
        policy = change.after.get("policy")
        if isinstance(policy, str):
            try:
                policy = json.loads(policy)
            except json.JSONDecodeError:
                return []
        if not isinstance(policy, dict):
            return []
        statements = policy.get("Statement", [])
        if isinstance(statements, dict):
            statements = [statements]
        if not isinstance(statements, list):
            return []
        if any(isinstance(statement, dict)
               and statement.get("Effect") == "Allow"
               and _has_wildcard(statement.get("Principal"))
               for statement in statements):
            return [self.finding(change, 'S3 bucket policy allows Principal "*".')]
        return []
