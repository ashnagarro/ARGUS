"""R002: deletion protection disabled."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class DeletionProtectionDisabled(Rule):
    id = "R002"
    title = "Deletion protection disabled"
    severity = "high"
    controls = ()
    source_doc_ids = ()

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        before = change.before or {}
        after = change.after or {}
        if before.get("deletion_protection") is True and after.get("deletion_protection") is False:
            return [self.finding(change, "Deletion protection changes from true to false.")]
        return []
