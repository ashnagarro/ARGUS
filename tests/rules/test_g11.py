"""G11 catches wildcard AWS principals in role trust policies."""

import json

from argus.models import Change
from argus.rules.g11 import WildcardAWSTrustPrincipal


def _change(policy: str) -> Change:
    return Change(
        address="aws_iam_role.synthetic", resource_type="aws_iam_role",
        canonical_type="aws_iam_role", actions=("create",),
        before=None, after={"assume_role_policy": policy},
        replace_paths=(), tags={}, is_replace=False,
    )


def test_wildcard_aws_trust_triggers() -> None:
    change = _change(json.dumps({"Statement": {
        "Effect": "Allow", "Action": "sts:AssumeRole",
        "Principal": {"AWS": ["arn:aws:iam::111122223333:root", "*"]},
    }}))
    findings = WildcardAWSTrustPrincipal().check(change, [change])
    assert len(findings) == 1
    assert findings[0].rule_id == "G11"


def test_scoped_or_deny_trust_does_not_trigger() -> None:
    rule = WildcardAWSTrustPrincipal()
    scoped = _change(json.dumps({"Statement": {
        "Effect": "Allow", "Action": "sts:AssumeRole",
        "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
    }}))
    deny = _change(json.dumps({"Statement": {
        "Effect": "Deny", "Action": "sts:AssumeRole",
        "Principal": {"AWS": "*"},
    }}))
    assert rule.check(scoped, [scoped]) == []
    assert rule.check(deny, [deny]) == []
    assert rule.check(_change("{"), []) == []


def test_sts_wildcard_action_with_wildcard_principal_triggers() -> None:
    change = _change(json.dumps({"Statement": {
        "Effect": "Allow", "Action": "sts:*", "Principal": {"AWS": "*"},
    }}))
    assert len(WildcardAWSTrustPrincipal().check(change, [change])) == 1
