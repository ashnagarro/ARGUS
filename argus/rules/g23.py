"""G23: check instance sizes against organization policy."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class AllowedInstanceClass(ContextRule):
    id = "G23"
    title = "Instance class not allowed"
    severity = "high"
    why_it_matters = "Unapproved instance classes bypass the team's sizing policy."
    how_to_fix = "Choose an instance class in the organization's allowed list."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        findings = []
        if not context.allowed_instance_classes:
            return findings
        for change in changes:
            after = change.after or {}
            size = after.get("instance_class") or after.get("instance_type")
            if isinstance(size, str) and size and size not in context.allowed_instance_classes:
                findings.append(context_finding(
                    self, change.address, f"Instance class {size} is not in the allowed list.",
                ))
        return findings
