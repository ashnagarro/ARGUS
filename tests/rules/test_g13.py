"""G13 catches disabled or deleted CloudTrail logging."""

from argus.models import Change
from argus.rules.g13 import CloudTrailLoggingOff


def _change(actions: tuple[str, ...], after: dict | None) -> Change:
    return Change(
        address="aws_cloudtrail.synthetic", resource_type="aws_cloudtrail",
        canonical_type="aws_cloudtrail", actions=actions,
        before={"enable_logging": True}, after=after,
        replace_paths=(), tags={}, is_replace=False,
    )


def test_cloudtrail_logging_disabled_triggers() -> None:
    change = _change(("update",), {"enable_logging": False})
    findings = CloudTrailLoggingOff().check(change, [change])
    assert len(findings) == 1
    assert findings[0].rule_id == "G13"


def test_cloudtrail_deletion_triggers() -> None:
    change = _change(("delete",), None)
    assert len(CloudTrailLoggingOff().check(change, [change])) == 1


def test_logging_stays_on_does_not_trigger() -> None:
    change = _change(("update",), {"enable_logging": True})
    assert CloudTrailLoggingOff().check(change, [change]) == []
