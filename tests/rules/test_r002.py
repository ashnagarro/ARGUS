"""R002 detects only a true-to-false deletion-protection transition."""

from dataclasses import replace

from argus.models import Change
from argus.rules.r002 import DeletionProtectionDisabled


def protected_database() -> Change:
    return Change(
        address="aws_db_instance.synthetic",
        resource_type="aws_db_instance",
        canonical_type="database_instance",
        actions=("update",),
        before={"deletion_protection": True},
        after={"deletion_protection": False},
        replace_paths=(),
        tags={},
        is_replace=False,
    )


def test_deletion_protection_off_triggers() -> None:
    change = protected_database()

    findings = DeletionProtectionDisabled().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "R002"
    assert findings[0].severity == "high"


def test_deletion_protection_stays_on_does_not_trigger() -> None:
    change = replace(protected_database(), after={"deletion_protection": True})

    assert DeletionProtectionDisabled().check(change, [change]) == []
