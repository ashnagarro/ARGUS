"""G02 detects disabled S3 public access block settings."""

from dataclasses import replace

from argus.models import Change
from argus.rules.g02 import S3PublicAccessBlockDisabled


def _block(restrict: bool) -> Change:
    return Change(
        address="aws_s3_bucket_public_access_block.fake",
        resource_type="aws_s3_bucket_public_access_block",
        canonical_type="aws_s3_bucket_public_access_block", actions=("update",),
        before={"restrict_public_buckets": True},
        after={"block_public_acls": True, "ignore_public_acls": True,
               "block_public_policy": True, "restrict_public_buckets": restrict},
        replace_paths=(), tags={}, is_replace=False,
    )


def test_disabled_public_access_block_triggers() -> None:
    change = _block(False)

    findings = S3PublicAccessBlockDisabled().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G02"
    assert findings[0].severity == "high"
    assert "restrict_public_buckets" in findings[0].message


def test_enabled_or_deleted_public_access_block_does_not_trigger() -> None:
    enabled = _block(True)
    deleted = replace(_block(False), actions=("delete",), after=None)

    assert S3PublicAccessBlockDisabled().check(enabled, [enabled]) == []
    assert S3PublicAccessBlockDisabled().check(deleted, [deleted]) == []
