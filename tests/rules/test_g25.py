"""G25 keeps change authors and approvers distinct."""

from argus.governance import GovernanceContext
from argus.rules.g25 import SeparationOfDuties


def test_self_approval_triggers(governance_change) -> None:
    change = governance_change()
    context = GovernanceContext(author="agent:synthetic", approver="synthetic")
    assert SeparationOfDuties().check_context((change,), context)[0].rule_id == "G25"


def test_distinct_approver_does_not_trigger(governance_change) -> None:
    change = governance_change()
    context = GovernanceContext(author="agent:synthetic", approver="reviewer-synthetic")
    assert SeparationOfDuties().check_context((change,), context) == []
