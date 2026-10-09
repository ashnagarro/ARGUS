"""G13: CloudTrail logging disabled or a trail deleted."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class CloudTrailLoggingOff(Rule):
    id = "G13"
    name = "audit-logging-disabled"
    title = "Audit logging disabled"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Without CloudTrail logging, activity on affected resources may lack an audit trail."
    how_to_fix = "Keep the trail and set enable_logging = true."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_cloudtrail":
            return []
        if change.after is None and "delete" in change.actions:
            return [self.finding(change, "Terraform deletes a CloudTrail trail.")]
        if change.after is not None and change.after.get("enable_logging") is False:
            return [self.finding(change, "CloudTrail enable_logging is false.")]
        return []
