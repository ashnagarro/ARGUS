"""R001: stateful infrastructure replacement."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class StatefulReplacement(Rule):
    id = "R001"
    name = "data-store-replacement"
    title = "Data store will be destroyed and recreated"
    applies_to = ("terraform/aws",)
    severity = "critical"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "Replacing a data store destroys the current resource and may lose its stored data."
    how_to_fix = ("Keep the original identifier; if a rename is required, plan a snapshot-and-restore "
                  "migration; add lifecycle { prevent_destroy = true } to stateful resources.")

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if not change.is_replace or change.canonical_type != "data_store":
            return []
        attributes = [".".join(map(str, path)) for path in change.replace_paths]
        cause = ", ".join(attributes) if attributes else "an unspecified attribute"
        return [self.finding(change, f"Replacement of a stateful resource is triggered by {cause}.")]
