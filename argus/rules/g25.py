"""G25: keep the change author and approver distinct."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class SeparationOfDuties(ContextRule):
    id = "G25"
    title = "Author is also approver"
    severity = "critical"
    why_it_matters = "Self-approval removes independent review of a change."
    how_to_fix = "Use a different human approver for this change."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        if not context.approver:
            return []
        author = context.author.strip().lower().removeprefix("agent:")
        approver = context.approver.strip().lower().removeprefix("agent:")
        if author and author == approver:
            return [context_finding(self, "change-review", "Change author and approver are the same identity.")]
        return []
