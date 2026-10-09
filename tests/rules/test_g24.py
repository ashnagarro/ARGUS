"""G24 requires a ticket for a production change."""

from argus.governance import GovernanceContext
from argus.rules.g24 import ProductionTicket


def test_production_without_ticket_triggers(governance_change) -> None:
    change = governance_change(tags={"env": "prod"})
    assert ProductionTicket().check_context((change,), GovernanceContext())[0].rule_id == "G24"


def test_production_with_ticket_does_not_trigger(governance_change) -> None:
    change = governance_change(tags={"env": "prod"})
    assert ProductionTicket().check_context((change,), GovernanceContext(ticket="SYNTH-1")) == []
