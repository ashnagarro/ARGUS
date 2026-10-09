"""G15: GuardDuty monitoring is disabled or its detector is deleted."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class G15GuardDutyDisabled(Rule):
    id = "G15"
    name = "threat-monitoring-disabled"
    title = "Threat monitoring disabled"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Disabling GuardDuty stops threat detection for the affected region."
    how_to_fix = "Keep the aws_guardduty_detector resource and set enable = true."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_guardduty_detector":
            return []
        if "delete" in change.actions and change.after is None:
            return [self.finding(change, "The GuardDuty detector will be deleted.")]
        if change.after is not None and change.after.get("enable") is False:
            return [self.finding(change, "GuardDuty detector enable is false.")]
        return []
