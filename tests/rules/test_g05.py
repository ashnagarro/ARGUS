"""G05 detects unencrypted EBS volumes."""

from dataclasses import replace

from argus.models import Change
from argus.rules.g05 import UnencryptedEBSVolume


def _volume(encrypted: bool) -> Change:
    return Change(
        address="aws_ebs_volume.fake", resource_type="aws_ebs_volume",
        canonical_type="block_volume", actions=("create",),
        before=None, after={"encrypted": encrypted},
        replace_paths=(), tags={}, is_replace=False,
    )


def test_unencrypted_volume_triggers() -> None:
    change = _volume(False)

    findings = UnencryptedEBSVolume().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "G05"
    assert findings[0].severity == "high"
    assert findings[0].resource == change.address


def test_encrypted_or_deleted_volume_does_not_trigger() -> None:
    encrypted = _volume(True)
    deleted = replace(_volume(False), actions=("delete",), after=None)

    assert UnencryptedEBSVolume().check(encrypted, [encrypted]) == []
    assert UnencryptedEBSVolume().check(deleted, [deleted]) == []
