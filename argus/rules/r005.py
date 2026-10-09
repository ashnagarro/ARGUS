"""R005: storage encryption disabled."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class StorageEncryptionDisabled(Rule):
    id = "R005"
    name = "encryption-at-rest-disabled"
    title = "Encryption at rest disabled"
    applies_to = ("terraform/aws",)
    severity = "high"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "Disabling storage encryption leaves stored data without encryption at rest."
    how_to_fix = "Keep storage_encrypted = true or encrypted = true on the affected resource."

    _encryption_fields = ("storage_encrypted", "encrypted")

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.canonical_type not in {"data_store", "encryption_config"}:
            return []
        before = change.before or {}
        after = change.after or {}
        for field in self._encryption_fields:
            if before.get(field) is True and after.get(field) is False:
                return [self.finding(change, f"{field} changes from true to false.")]
        return []
