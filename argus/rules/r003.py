"""R003: database plans must retain a final snapshot on deletion."""

from collections.abc import Sequence

from argus.models import Change
from argus.rules import Rule, RuleFinding


class R003SkipFinalSnapshot(Rule):
    id = "R003"
    title = "Database final snapshot skipped"
    severity = "high"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "Skipping the final snapshot can leave no restore point when the database is deleted."
    how_to_fix = "Set skip_final_snapshot = false and configure final_snapshot_identifier before deletion."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        """Flag a database configured to skip its final snapshot."""
        if change.canonical_type not in {"database_instance", "database_cluster"}:
            return []

        after_skips = change.after is not None and change.after.get("skip_final_snapshot") is True
        deleted_before_skips = (
            "delete" in change.actions
            and change.before is not None
            and change.before.get("skip_final_snapshot") is True
        )
        if not after_skips and not deleted_before_skips:
            return []

        return [self.finding(
            change,
            "skip_final_snapshot is true for this database; deletion can omit its final snapshot.",
        )]
