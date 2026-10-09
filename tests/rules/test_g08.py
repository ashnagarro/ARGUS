"""G08 catches unrestricted IAM policy statements."""

import json

from argus.models import Change
from argus.rules.g08 import IAMUnrestrictedPolicy


def _change(policy: str) -> Change:
    return Change(
        address="aws_iam_policy.synthetic", resource_type="aws_iam_policy",
        canonical_type="aws_iam_policy", actions=("create",),
        before=None, after={"policy": policy}, replace_paths=(),
        tags={}, is_replace=False,
    )


def test_allow_all_actions_and_resources_triggers() -> None:
    change = _change(json.dumps({"Statement": [
        {"Effect": "Allow", "Action": ["s3:GetObject", "*"], "Resource": ["*"]}
    ]}))
    findings = IAMUnrestrictedPolicy().check(change, [change])
    assert len(findings) == 1
    assert findings[0].rule_id == "G08"
    assert findings[0].severity == "critical"


def test_scoped_or_deny_policy_does_not_trigger() -> None:
    rule = IAMUnrestrictedPolicy()
    scoped = _change(json.dumps({"Statement": [
        {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"}
    ]}))
    deny = _change(json.dumps({"Statement": [
        {"Effect": "Deny", "Action": "*", "Resource": "*"}
    ]}))
    assert rule.check(scoped, [scoped]) == []
    assert rule.check(deny, [deny]) == []
    assert rule.check(_change("{"), []) == []
