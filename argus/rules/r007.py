"""R007: SQL Server major upgrades need a new parameter group.

Evidence: rds-sqlserver-upgrade-considerations (retrieved_at 2026-10-09).
"""

from typing import Sequence

from argus.models import Change, RuleFinding
from argus.rules import Rule


def _major_version(version: object) -> int | None:
    if not isinstance(version, str):
        return None
    major = version.split(".", 1)[0]
    return int(major) if major.isdecimal() else None


class SqlServerMajorUpgradeParameterGroup(Rule):
    id = "R007"
    title = "SQL Server major upgrade retains parameter group"
    severity = "high"
    source_doc_ids = ("rds-sqlserver-upgrade-considerations",)
    why_it_matters = "A major SQL Server upgrade using the old custom parameter group can apply incompatible settings."
    how_to_fix = ("Create a parameter group for the target major version, preserve the required custom "
                  "settings, and update parameter_group_name in the same Terraform change.")
    source_finding_id = "F1"
    human_approved_on = "2026-10-09"

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        if (change.resource_type != "aws_db_instance"
                or change.canonical_type != "database_instance"
                or change.actions != ("update",)):
            return []
        before = change.before or {}
        after = change.after or {}
        engine = before.get("engine")
        if not (isinstance(engine, str) and engine.startswith("sqlserver-")
                and after.get("engine") == engine):
            return []

        old_major = _major_version(before.get("engine_version"))
        new_major = _major_version(after.get("engine_version"))
        if old_major is None or new_major is None or new_major <= old_major:
            return []

        old_group = before.get("parameter_group_name")
        new_group = after.get("parameter_group_name")
        if not (isinstance(old_group, str) and old_group
                and not old_group.startswith("default.")
                and isinstance(new_group, str) and new_group == old_group):
            return []

        return [self.finding(
            change,
            f"SQL Server major version increases from {before['engine_version']} "
            f"to {after['engine_version']}, but parameter group {old_group!r} "
            "remains unchanged. Specify a new parameter group for the upgrade.",
        )]
