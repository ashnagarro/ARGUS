"""R006 detects reduced backup retention."""

from argus.models import Change
from argus.rules.r006 import BackupRetentionReduced


def _change(before: object, after: object) -> Change:
    return Change(
        address="aws_db_instance.fake",
        resource_type="aws_db_instance",
        canonical_type="database_instance",
        actions=("update",),
        before={"backup_retention_period": before},
        after={"backup_retention_period": after},
        replace_paths=(),
        tags={},
        is_replace=False,
    )


def test_backup_retention_reduction_triggers() -> None:
    change = _change(14, 7)

    findings = BackupRetentionReduced().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "R006"
    assert findings[0].resource == change.address
    assert findings[0].severity == "high"
    assert "14 to 7" in findings[0].message


def test_backup_retention_increase_does_not_trigger() -> None:
    change = _change(7, 14)

    assert BackupRetentionReduced().check(change, [change]) == []


def test_boolean_retention_values_do_not_trigger() -> None:
    change = _change(True, False)

    assert BackupRetentionReduced().check(change, [change]) == []
