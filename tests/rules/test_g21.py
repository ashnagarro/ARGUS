"""G21 requires only tags named by organization configuration."""

from argus.governance import GovernanceContext
from argus.rules.g21 import RequiredTags


def test_missing_required_tag_triggers(governance_change) -> None:
    change = governance_change(tags={"env": "prod"})
    findings = RequiredTags().check_context((change,), GovernanceContext(required_tags=("env", "owner")))
    assert len(findings) == 1 and findings[0].rule_id == "G21"
    assert "owner" in findings[0].message


def test_all_required_tags_present_does_not_trigger(governance_change) -> None:
    change = governance_change(tags={"env": "prod", "owner": "synthetic-team"})
    assert RequiredTags().check_context((change,), GovernanceContext(required_tags=("env", "owner"))) == []
