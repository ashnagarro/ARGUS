"""G01: publicly accessible database instances."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class PublicDatabaseAccess(Rule):
    id = "G01"
    name = "data-store-publicly-accessible"
    title = "Data store is publicly accessible"
    applies_to = ("terraform/aws",)
    severity = "critical"
    why_it_matters = "A public database endpoint can be reached from outside the private network."
    how_to_fix = "Set publicly_accessible = false and use private network access."

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if (change.resource_type == "aws_db_instance" and change.after is not None
                and change.after.get("publicly_accessible") is True):
            return [self.finding(change, "Database publicly_accessible is true.")]
        return []
