"""G28 requires human review of sensitive agent changes."""

from argus.governance import GovernanceContext
from argus.rules.g28 import SensitiveAgentApproval


def test_agent_iam_change_without_approver_triggers(governance_change) -> None:
    change = governance_change(resource_type="aws_iam_policy")
    assert SensitiveAgentApproval().check_context((change,), GovernanceContext(author="agent:synthetic"))[0].rule_id == "G28"


def test_distinct_human_approver_satisfies_rule(governance_change) -> None:
    change = governance_change(resource_type="aws_iam_policy")
    context = GovernanceContext(author="agent:synthetic", approver="reviewer-synthetic")
    assert SensitiveAgentApproval().check_context((change,), context) == []
