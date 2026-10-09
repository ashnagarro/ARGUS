"""G07: encryption disabled on classified storage."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule

from ._governance import tag_values


class ClassifiedStorageEncryptionDisabled(Rule):
    id = "G07"
    name = "classified-data-unencrypted"
    title = "Classified data lacks encryption at rest"
    applies_to = ("terraform/aws",)
    severity = "critical"
    why_it_matters = "Classified data on unencrypted storage has a greater exposure risk."
    how_to_fix = "Enable encryption for the storage resource before applying the change."

    _fields = {
        "aws_db_instance": "storage_encrypted",
        "aws_ebs_volume": "encrypted",
    }

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        field = self._fields.get(change.resource_type)
        classifications = tag_values(change, "data_classification")
        if (field is not None and classifications
                and change.after is not None and change.after.get(field) is False):
            return [self.finding(
                change,
                f"{field} is false on a resource classified as {classifications[0]!r}.",
            )]
        return []
