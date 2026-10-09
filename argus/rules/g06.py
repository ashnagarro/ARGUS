"""G06: KMS key rotation disabled or a key deleted."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class KMSKeyProtection(Rule):
    id = "G06"
    title = "KMS key protection reduced"
    severity = "critical"
    why_it_matters = "Deleting a KMS key or disabling its rotation weakens protection of encrypted data."
    how_to_fix = "Retain the KMS key and set enable_key_rotation = true."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if change.resource_type != "aws_kms_key":
            return []
        if "delete" in change.actions and "create" not in change.actions:
            return [self.finding(change, "KMS key is deleted.")]
        if change.after is not None and change.after.get("enable_key_rotation") is False:
            return [self.finding(change, "KMS key rotation is disabled.")]
        return []
