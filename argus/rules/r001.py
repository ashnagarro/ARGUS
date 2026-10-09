"""R001: stateful infrastructure replacement."""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


class StatefulReplacement(Rule):
    id = "R001"
    title = "Stateful resource replacement"
    severity = "critical"
    controls = ()
    source_doc_ids = ()
    why_it_matters = "Replacing a database deletes it and its data, then creates an empty one."
    how_to_fix = ("Keep the original identifier; if a rename is required, plan a snapshot-and-restore "
                  "migration; add lifecycle { prevent_destroy = true } to stateful resources.")

    _stateful_types = frozenset({"database_instance", "database_cluster", "block_volume"})

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if not change.is_replace or change.canonical_type not in self._stateful_types:
            return []
        attributes = [".".join(map(str, path)) for path in change.replace_paths]
        cause = ", ".join(attributes) if attributes else "an unspecified attribute"
        return [self.finding(change, f"Replacement of a stateful resource is triggered by {cause}.")]
