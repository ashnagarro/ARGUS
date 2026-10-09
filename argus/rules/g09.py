"""G09: creation of a long-lived IAM access key."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class IAMAccessKeyCreated(Rule):
    id = "G09"
    name = "long-lived-access-key-created"
    title = "Long-lived access key created"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "A long-lived access key can be copied and used outside its intended workload."
    how_to_fix = "Use a role with temporary credentials where possible; otherwise manage and rotate the key securely."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type == "aws_iam_access_key" and "create" in change.actions:
            return [self.finding(change, "Terraform creates an IAM access key.")]
        return []
