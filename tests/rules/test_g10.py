"""G10 catches AdministratorAccess newly attached to IAM users."""

from argus.models import Change
from argus.rules.g10 import AdministratorAccessOnUser


_ADMIN = "arn:aws:iam::aws:policy/AdministratorAccess"
_READ_ONLY = "arn:aws:iam::aws:policy/ReadOnlyAccess"


def _change(resource_type: str, before: dict | None, after: dict) -> Change:
    return Change(
        address=f"{resource_type}.synthetic", resource_type=resource_type,
        canonical_type=resource_type,
        actions=("create",) if before is None else ("update",),
        before=before, after=after, replace_paths=(), tags={}, is_replace=False,
    )


def test_administrator_access_user_attachment_triggers() -> None:
    change = _change("aws_iam_user_policy_attachment", None,
                     {"user": "synthetic", "policy_arn": _ADMIN})
    findings = AdministratorAccessOnUser().check(change, [change])
    assert len(findings) == 1
    assert findings[0].rule_id == "G10"
    assert "synthetic" in findings[0].message


def test_bulk_policy_attachment_to_new_user_triggers() -> None:
    change = _change(
        "aws_iam_policy_attachment",
        {"users": ["original"], "policy_arn": _ADMIN},
        {"users": ["original", "synthetic"], "policy_arn": _ADMIN},
    )
    assert len(AdministratorAccessOnUser().check(change, [change])) == 1


def test_read_only_or_unchanged_admin_attachment_does_not_trigger() -> None:
    rule = AdministratorAccessOnUser()
    read_only = _change("aws_iam_user_policy_attachment", None,
                        {"user": "synthetic", "policy_arn": _READ_ONLY})
    unchanged = _change(
        "aws_iam_user_policy_attachment",
        {"user": "synthetic", "policy_arn": _ADMIN},
        {"user": "synthetic", "policy_arn": _ADMIN},
    )
    assert rule.check(read_only, [read_only]) == []
    assert rule.check(unchanged, [unchanged]) == []
