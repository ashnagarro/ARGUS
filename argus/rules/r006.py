"""R006: database backup retention reduced."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class BackupRetentionReduced(Rule):
    id = "R006"
    title = "Backup retention reduced"
    severity = "high"
    controls = ()
    source_doc_ids = ()

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        before = (change.before or {}).get("backup_retention_period")
        after = (change.after or {}).get("backup_retention_period")
        if type(before) is int and type(after) is int and before > after:
            return [self.finding(
                change,
                f"backup_retention_period decreases from {before} to {after}.",
            )]
        return []
