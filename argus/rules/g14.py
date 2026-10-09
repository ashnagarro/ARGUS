"""G14: deletion of a VPC flow log."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class FlowLogDeleted(Rule):
    id = "G14"
    name = "network-flow-logging-removed"
    title = "Network flow logging removed"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Deleting a flow log removes network traffic records used for investigation."
    how_to_fix = "Keep the flow log or create an equivalent replacement before removing it."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if (change.resource_type == "aws_flow_log"
                and change.after is None and "delete" in change.actions):
            return [self.finding(change, "Terraform deletes a VPC flow log.")]
        return []
