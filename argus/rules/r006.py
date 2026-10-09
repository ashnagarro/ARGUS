"""R006: database backup retention reduced."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class BackupRetentionReduced(Rule):
    id = "R006"
    name = "backup-retention-reduced"
    title = "Backup retention reduced"
    applies_to = ("terraform/aws",)
    severity = "high"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "Shorter backup retention reduces the time available to restore lost data."
    how_to_fix = "Keep backup_retention_period at or above its previous value."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.canonical_type not in {"data_store", "backup_config"}:
            return []
        before = (change.before or {}).get("backup_retention_period")
        after = (change.after or {}).get("backup_retention_period")
        if type(before) is int and type(after) is int and before > after:
            return [self.finding(
                change,
                f"backup_retention_period decreases from {before} to {after}.",
            )]
        return []
