"""G08: IAM policies granting every action on every resource."""

import json
from collections.abc import Sequence
from typing import Any

from argus.models import Change, RuleFinding
from argus.rules import Rule


_IAM_POLICY_TYPES = frozenset({
    "aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy",
    "aws_iam_group_policy",
})


def _policy(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _has_wildcard(value: object) -> bool:
    return value == "*" or isinstance(value, list) and "*" in value


class IAMUnrestrictedPolicy(Rule):
    id = "G08"
    title = "IAM policy grants all actions on all resources"
    severity = "critical"
    why_it_matters = "An unrestricted IAM policy can grant control over every supported AWS resource."
    how_to_fix = "Replace wildcard actions and resources with the specific permissions the identity needs."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type not in _IAM_POLICY_TYPES or change.after is None:
            return []
        policy = _policy(change.after.get("policy"))
        if policy is None:
            return []
        statements = policy.get("Statement", [])
        if isinstance(statements, dict):
            statements = [statements]
        if not isinstance(statements, list):
            return []
        for statement in statements:
            if (isinstance(statement, dict)
                    and str(statement.get("Effect", "")).lower() == "allow"
                    and _has_wildcard(statement.get("Action"))
                    and _has_wildcard(statement.get("Resource"))):
                return [self.finding(change, "An Allow statement grants Action '*' on Resource '*'.")]
        return []
