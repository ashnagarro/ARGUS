"""G11: an IAM role trust policy accepting every AWS principal."""

import json
from collections.abc import Sequence
from typing import Any

from argus.models import Change, RuleFinding
from argus.rules import Rule


def _policy(value: object) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _has_wildcard(value: object) -> bool:
    return value == "*" or isinstance(value, list) and "*" in value


def _assume_role(value: object) -> bool:
    actions = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return any(isinstance(action, str)
               and action.lower() in ("sts:assumerole", "sts:*", "*") for action in actions)


class WildcardAWSTrustPrincipal(Rule):
    id = "G11"
    name = "role-trust-allows-any-principal"
    title = "Role trust allows any principal"
    applies_to = ("terraform/aws",)
    severity = "critical"
    why_it_matters = "A wildcard AWS principal can make a role assumable by identities beyond the intended trust boundary."
    how_to_fix = "List the intended AWS principals explicitly and restrict role assumption with conditions."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_iam_role" or change.after is None:
            return []
        policy = _policy(change.after.get("assume_role_policy"))
        if policy is None:
            return []
        statements = policy.get("Statement", [])
        if isinstance(statements, dict):
            statements = [statements]
        if not isinstance(statements, list):
            return []
        for statement in statements:
            if not isinstance(statement, dict) or str(statement.get("Effect", "")).lower() != "allow":
                continue
            principal = statement.get("Principal")
            if (isinstance(principal, dict)
                    and _has_wildcard(principal.get("AWS"))
                    and _assume_role(statement.get("Action"))):
                return [self.finding(change, "The role trust policy allows sts:AssumeRole by AWS principal '*'.")]
        return []
