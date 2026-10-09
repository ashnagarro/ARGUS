"""G29: agent changes must have a durable ledger entry."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class AgentLedgerEntry(ContextRule):
    id = "G29"
    title = "Agent change has no ledger entry"
    severity = "critical"
    why_it_matters = "An agent change without a ledger record cannot be audited."
    how_to_fix = "Record the agent review and its verdict in the ARGUS ledger."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        if context.author.startswith("agent:") and changes and not context.ledger_recorded:
            return [context_finding(self, "ledger/ledger.jsonl", "Agent change has no durable ledger entry.")]
        return []
