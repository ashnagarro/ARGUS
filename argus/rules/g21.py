"""G21: require organization-defined resource tags."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class RequiredTags(ContextRule):
    id = "G21"
    title = "Required tags missing"
    severity = "high"
    why_it_matters = "Missing ownership or classification tags prevent consistent review."
    how_to_fix = "Add every tag required by the organization's governance configuration."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        findings = []
        for change in changes:
            if "delete" in change.actions and "create" not in change.actions:
                continue
            missing = [tag for tag in context.required_tags if not change.tags.get(tag)]
            if missing:
                findings.append(context_finding(
                    self, change.address, f"Missing required tags: {', '.join(missing)}.",
                ))
        return findings
