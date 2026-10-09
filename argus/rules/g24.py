"""G24: require a ticket for resources tagged production before or after a change."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule, is_production


class ProductionTicket(ContextRule):
    id = "G24"
    name = "production-change-without-ticket"
    title = "Production change has no ticket"
    applies_to = ("terraform/aws",)
    severity = "critical"
    why_it_matters = "A production change without a ticket lacks a review reference."
    how_to_fix = "Provide the production change ticket with --ticket."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        if context.ticket and context.ticket.strip():
            return []
        return [context_finding(self, change.address, "Production change has no --ticket reference.")
                for change in changes if is_production(change)]
