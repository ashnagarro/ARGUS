"""R005 detects storage encryption being turned off."""

import pytest

from argus.models import Change
from argus.rules.r005 import StorageEncryptionDisabled


def _change(resource_type: str, canonical_type: str, before: dict, after: dict) -> Change:
    return Change(
        address=f"{resource_type}.fake",
        resource_type=resource_type,
        canonical_type=canonical_type,
        actions=("update",),
        before=before,
        after=after,
        replace_paths=(),
        tags={},
        is_replace=False,
    )


@pytest.mark.parametrize(
    ("resource_type", "canonical_type", "field"),
    [
        ("aws_db_instance", "database_instance", "storage_encrypted"),
        ("aws_ebs_volume", "block_volume", "encrypted"),
    ],
)
def test_encryption_disabled_triggers(resource_type: str, canonical_type: str, field: str) -> None:
    change = _change(resource_type, canonical_type, {field: True}, {field: False})

    findings = StorageEncryptionDisabled().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "R005"
    assert findings[0].resource == change.address
    assert findings[0].severity == "high"
    assert field in findings[0].message


def test_encryption_remaining_enabled_does_not_trigger() -> None:
    change = _change(
        "aws_db_instance",
        "database_instance",
        {"storage_encrypted": True},
        {"storage_encrypted": True},
    )

    assert StorageEncryptionDisabled().check(change, [change]) == []
