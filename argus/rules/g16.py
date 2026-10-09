"""G16: an AWS Config recorder is stopped."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class G16ConfigRecorderStopped(Rule):
    id = "G16"
    title = "AWS Config recorder stopped"
    severity = "high"
    why_it_matters = "A stopped recorder cannot capture configuration changes for review."
    how_to_fix = "Keep aws_config_configuration_recorder_status and set is_enabled = true."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_config_configuration_recorder_status":
            return []
        if "delete" in change.actions and change.after is None:
            return [self.finding(change, "The configuration recorder status will be deleted.")]
        if change.after is not None and change.after.get("is_enabled") is False:
            return [self.finding(change, "Configuration recorder is_enabled is false.")]
        return []
