"""G07 raises classified storage without encryption to critical."""

import pytest
from dataclasses import replace

from argus.models import Change
from argus.rules.g07 import ClassifiedStorageEncryptionDisabled


def _storage(resource_type: str, field: str, encrypted: bool, classified: bool) -> Change:
    return Change(
        address=f"{resource_type}.fake", resource_type=resource_type,
        canonical_type="database_instance" if resource_type == "aws_db_instance" else "block_volume",
        actions=("update",), before={field: True}, after={field: encrypted},
        replace_paths=(),
        tags={"data_classification": "fake-confidential"} if classified else {},
        is_replace=False,
    )


@pytest.mark.parametrize(("resource_type", "field"), [
    ("aws_db_instance", "storage_encrypted"),
    ("aws_ebs_volume", "encrypted"),
])
def test_classified_storage_without_encryption_triggers(
    resource_type: str, field: str,
) -> None:
    change = _storage(resource_type, field, False, True)

    findings = ClassifiedStorageEncryptionDisabled().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G07"
    assert findings[0].severity == "critical"
    assert findings[0].tags == {"data_classification": "fake-confidential"}


def test_unclassified_encrypted_or_deleted_storage_does_not_trigger() -> None:
    unclassified = _storage("aws_ebs_volume", "encrypted", False, False)
    encrypted = _storage("aws_db_instance", "storage_encrypted", True, True)
    deleted = replace(_storage("aws_ebs_volume", "encrypted", False, True),
                      actions=("delete",), after=None)

    rule = ClassifiedStorageEncryptionDisabled()
    for change in (unclassified, encrypted, deleted):
        assert rule.check(change, [change]) == []
