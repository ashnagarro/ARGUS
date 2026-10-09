"""G10: AWS AdministratorAccess attached directly to an IAM user."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


def _administrator_access(value: object) -> bool:
    return isinstance(value, str) and value.endswith(":policy/AdministratorAccess")


class AdministratorAccessOnUser(Rule):
    id = "G10"
    title = "AdministratorAccess attached to an IAM user"
    severity = "critical"
    why_it_matters = "A user with AdministratorAccess can change almost any resource in the account."
    how_to_fix = "Use a narrowly scoped role with temporary credentials instead of direct user access."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        after = change.after
        if after is None or not _administrator_access(after.get("policy_arn")):
            return []
        before = change.before or {}
        if change.resource_type == "aws_iam_user_policy_attachment":
            user = after.get("user")
            if (isinstance(user, str) and user
                    and (not _administrator_access(before.get("policy_arn"))
                         or before.get("user") != user)):
                return [self.finding(change, f"AdministratorAccess is attached to IAM user {user}.")]
        elif change.resource_type == "aws_iam_policy_attachment":
            users = after.get("users")
            old_users = before.get("users")
            if isinstance(users, list):
                added = {user for user in users if isinstance(user, str) and user}
                if (_administrator_access(before.get("policy_arn"))
                        and isinstance(old_users, list)):
                    added -= {user for user in old_users if isinstance(user, str) and user}
                if added:
                    return [self.finding(
                        change, f"AdministratorAccess is attached to IAM user {sorted(added)[0]}."
                    )]
        return []
