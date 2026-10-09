"""G18: production RDS Multi-AZ availability is switched off."""

from collections.abc import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class G18ProductionMultiAzDisabled(Rule):
    id = "G18"
    title = "Production database Multi-AZ disabled"
    severity = "high"
    why_it_matters = "Removing Multi-AZ from a production database reduces its failure resilience."
    how_to_fix = "Keep multi_az = true on the production aws_db_instance."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_db_instance":
            return []
        if change.tags.get("env", "").lower() not in {"prod", "production"}:
            return []
        before = change.before or {}
        after = change.after or {}
        if before.get("multi_az") is True and after.get("multi_az") is False:
            return [self.finding(change, "Production database multi_az changes from true to false.")]
        return []
