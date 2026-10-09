"""G09 catches planned IAM access key creation."""

from argus.models import Change
from argus.rules.g09 import IAMAccessKeyCreated


def _change(resource_type: str, actions: tuple[str, ...]) -> Change:
    return Change(
        address=f"{resource_type}.synthetic", resource_type=resource_type,
        canonical_type=resource_type, actions=actions,
        before=None if "create" in actions else {"user": "synthetic"},
        after={"user": "synthetic"}, replace_paths=(), tags={},
        is_replace=False,
    )


def test_access_key_creation_triggers() -> None:
    change = _change("aws_iam_access_key", ("create",))
    findings = IAMAccessKeyCreated().check(change, [change])
    assert len(findings) == 1
    assert findings[0].rule_id == "G09"


def test_access_key_update_and_other_resource_do_not_trigger() -> None:
    rule = IAMAccessKeyCreated()
    update = _change("aws_iam_access_key", ("update",))
    other = _change("aws_iam_user", ("create",))
    assert rule.check(update, [update]) == []
    assert rule.check(other, [other]) == []
