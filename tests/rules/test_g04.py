"""G04 detects deletion of S3 encryption configuration."""

from dataclasses import replace

from argus.models import Change
from argus.rules.g04 import S3EncryptionConfigurationDeleted


def _encryption_config() -> Change:
    return Change(
        address="aws_s3_bucket_server_side_encryption_configuration.fake",
        resource_type="aws_s3_bucket_server_side_encryption_configuration",
        canonical_type="aws_s3_bucket_server_side_encryption_configuration",
        actions=("delete",), before={"bucket": "fake"}, after=None,
        replace_paths=(), tags={}, is_replace=False,
    )


def test_encryption_config_deletion_triggers() -> None:
    change = _encryption_config()

    findings = S3EncryptionConfigurationDeleted().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G04"
    assert findings[0].severity == "high"
    assert findings[0].resource == change.address


def test_replacement_does_not_trigger() -> None:
    replacement = replace(_encryption_config(), actions=("delete", "create"),
                          after={"bucket": "fake"}, is_replace=True)

    assert S3EncryptionConfigurationDeleted().check(replacement, [replacement]) == []
