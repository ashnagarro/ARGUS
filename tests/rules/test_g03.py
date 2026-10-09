"""G03 parses S3 policy JSON and detects public Allow statements."""

import json
from dataclasses import replace

from argus.models import Change
from argus.rules.g03 import PublicS3BucketPolicy


def _policy(document: object) -> Change:
    return Change(
        address="aws_s3_bucket_policy.fake", resource_type="aws_s3_bucket_policy",
        canonical_type="aws_s3_bucket_policy", actions=("create",),
        before=None, after={"policy": document}, replace_paths=(), tags={}, is_replace=False,
    )


def test_wildcard_principal_in_json_policy_triggers() -> None:
    policy = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"AWS": "*"}, "Action": "s3:GetObject",
         "Resource": "arn:aws:s3:::fake/*"},
    ]})
    change = _policy(policy)

    findings = PublicS3BucketPolicy().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G03"
    assert findings[0].severity == "critical"
    assert 'Principal "*"' in findings[0].message


def test_private_and_deny_policies_do_not_trigger() -> None:
    private = _policy({"Statement": {"Effect": "Allow", "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/fake"}}})
    deny = _policy(json.dumps({"Statement": {"Effect": "Deny", "Principal": "*"}}))
    malformed = _policy("{bad json")
    deleted = replace(_policy({"Statement": {"Effect": "Allow", "Principal": "*"}}),
                      actions=("delete",), after=None)

    rule = PublicS3BucketPolicy()
    for change in (private, deny, malformed, deleted):
        assert rule.check(change, [change]) == []
