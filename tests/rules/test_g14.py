"""G14 catches VPC flow log deletion."""

from argus.models import Change
from argus.rules.g14 import FlowLogDeleted


def _change(resource_type: str, actions: tuple[str, ...], after: dict | None) -> Change:
    return Change(
        address=f"{resource_type}.synthetic", resource_type=resource_type,
        canonical_type=resource_type, actions=actions,
        before={"traffic_type": "ALL"}, after=after,
        replace_paths=(), tags={}, is_replace=False,
    )


def test_flow_log_deletion_triggers() -> None:
    change = _change("aws_flow_log", ("delete",), None)
    findings = FlowLogDeleted().check(change, [change])
    assert len(findings) == 1
    assert findings[0].rule_id == "G14"


def test_replacement_or_other_deletion_does_not_trigger() -> None:
    rule = FlowLogDeleted()
    replacement = _change("aws_flow_log", ("delete", "create"), {"traffic_type": "ALL"})
    other = _change("aws_cloudtrail", ("delete",), None)
    assert rule.check(replacement, [replacement]) == []
    assert rule.check(other, [other]) == []
