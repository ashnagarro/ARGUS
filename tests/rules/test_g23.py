"""G23 checks instance class only when a class policy is configured."""

from argus.governance import GovernanceContext
from argus.rules.g23 import AllowedInstanceClass


def test_unapproved_instance_class_triggers(governance_change) -> None:
    change = governance_change(after={"instance_class": "db.synthetic.large"})
    assert AllowedInstanceClass().check_context((change,), GovernanceContext(allowed_instance_classes=("db.synthetic.small",)))[0].rule_id == "G23"


def test_allowed_instance_class_does_not_trigger(governance_change) -> None:
    change = governance_change(after={"instance_class": "db.synthetic.small"})
    assert AllowedInstanceClass().check_context((change,), GovernanceContext(allowed_instance_classes=("db.synthetic.small",))) == []
