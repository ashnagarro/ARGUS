"""R002: deletion protection disabled."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class DeletionProtectionDisabled(Rule):
    id = "R002"
    name = "deletion-protection-disabled"
    title = "Deletion protection disabled on a data store"
    applies_to = ("terraform/aws",)
    severity = "high"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "Disabling deletion protection makes an accidental database deletion easier."
    how_to_fix = "Keep deletion_protection = true on the database resource."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.canonical_type != "data_store":
            return []
        before = change.before or {}
        after = change.after or {}
        if before.get("deletion_protection") is True and after.get("deletion_protection") is False:
            return [self.finding(change, "Deletion protection changes from true to false.")]
        return []
