"""G06 detects KMS rotation disabled and key deletion."""

from dataclasses import replace

from argus.models import Change
from argus.rules.g06 import KMSKeyProtection


def _key(rotation: bool) -> Change:
    return Change(
        address="aws_kms_key.fake", resource_type="aws_kms_key",
        canonical_type="aws_kms_key", actions=("update",),
        before={"enable_key_rotation": True}, after={"enable_key_rotation": rotation},
        replace_paths=(), tags={}, is_replace=False,
    )


def test_rotation_disabled_triggers() -> None:
    change = _key(False)

    findings = KMSKeyProtection().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G06"
    assert findings[0].severity == "critical"
    assert "rotation" in findings[0].message


def test_key_deletion_triggers() -> None:
    change = replace(_key(True), actions=("delete",), after=None)

    findings = KMSKeyProtection().check(change, [change])

    assert len(findings) == 1
    assert "deleted" in findings[0].message


def test_rotation_enabled_does_not_trigger() -> None:
    change = _key(True)

    assert KMSKeyProtection().check(change, [change]) == []
