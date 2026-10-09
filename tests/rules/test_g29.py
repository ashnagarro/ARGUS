"""G29 checks that agent reviews are recorded durably."""

from argus.governance import GovernanceContext
from argus.rules.g29 import AgentLedgerEntry


def test_agent_without_ledger_entry_triggers(governance_change) -> None:
    change = governance_change()
    context = GovernanceContext(author="agent:synthetic", ledger_recorded=False)
    assert AgentLedgerEntry().check_context((change,), context)[0].rule_id == "G29"


def test_recorded_agent_review_does_not_trigger(governance_change) -> None:
    change = governance_change()
    context = GovernanceContext(author="agent:synthetic", ledger_recorded=True)
    assert AgentLedgerEntry().check_context((change,), context) == []
