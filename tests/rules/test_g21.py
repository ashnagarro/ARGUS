"""G21 requires only tags named by organization configuration."""

from dataclasses import replace

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


def test_required_tag_removed_from_taggable_resource_triggers(governance_change) -> None:
    change = replace(
        governance_change(tags={"env": "prod"}),
        before={"tags": {"env": "prod", "owner": "synthetic-team"}},
        after={"tags": {"env": "prod"}},
    )

    findings = RequiredTags().check_context((change,), GovernanceContext(required_tags=("owner",)))

    assert [item.rule_id for item in findings] == ["G21"]


def test_untaggable_resource_does_not_get_impossible_tag_finding(governance_change) -> None:
    change = governance_change(
        resource_type="aws_s3_bucket_public_access_block",
        before={"block_public_policy": True}, after={"block_public_policy": False},
    )

    assert RequiredTags().check_context((change,), GovernanceContext(required_tags=("owner",))) == []
