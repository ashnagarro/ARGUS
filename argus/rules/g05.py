"""G05: EBS volumes without encryption."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class UnencryptedEBSVolume(Rule):
    id = "G05"
    name = "block-storage-unencrypted"
    title = "Block storage encryption disabled"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "An unencrypted EBS volume can store data without encryption at rest."
    how_to_fix = "Set encrypted = true on the EBS volume."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if (change.resource_type == "aws_ebs_volume" and change.after is not None
                and change.after.get("encrypted") is False):
            return [self.finding(change, "EBS volume encrypted is false.")]
        return []
