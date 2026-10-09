"""G20: a named AWS Backup plan rule is removed."""

from collections.abc import Sequence
from typing import Any

from argus.models import Change, RuleFinding
from argus.rules import Rule


def _rule_names(state: dict[str, Any] | None) -> set[str]:
    raw = (state or {}).get("rule")
    if isinstance(raw, dict):
        entries = [raw]
    elif isinstance(raw, list):
        entries = raw
    else:
        return set()
    return {
        name for item in entries if isinstance(item, dict)
        if isinstance((name := item.get("rule_name")), str) and name
    }


class G20BackupPlanRuleDeleted(Rule):
    id = "G20"
    name = "backup-schedule-removed"
    title = "Backup schedule removed"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Removing a backup plan rule can stop scheduled recovery points."
    how_to_fix = "Keep the named rule block in aws_backup_plan, or replace it with an approved backup schedule."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_backup_plan":
            return []
        removed = _rule_names(change.before) - _rule_names(change.after)
        if not removed:
            return []
        return [self.finding(change, f"Backup plan rule {name!r} will be removed.")
                for name in sorted(removed)]
