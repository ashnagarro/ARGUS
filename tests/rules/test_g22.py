"""G22 checks an explicit region against the configured allowlist."""

from argus.governance import GovernanceContext
from argus.rules.g22 import ApprovedRegion


def test_unapproved_region_triggers(governance_change) -> None:
    change = governance_change(after={"region": "synthetic-west"})
    assert ApprovedRegion().check_context((change,), GovernanceContext(approved_regions=("synthetic-east",)))[0].rule_id == "G22"


def test_approved_region_does_not_trigger(governance_change) -> None:
    change = governance_change(after={"region": "synthetic-east"})
    assert ApprovedRegion().check_context((change,), GovernanceContext(approved_regions=("synthetic-east",))) == []
