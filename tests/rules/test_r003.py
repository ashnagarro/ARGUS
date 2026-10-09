"""Positive and negative checks for R003."""

from argus.models import Change
from argus.rules.r003 import R003SkipFinalSnapshot


def _database_change(
    *,
    actions: tuple[str, ...],
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> Change:
    return Change(
        address="aws_db_instance.synthetic",
        resource_type="aws_db_instance",
        canonical_type="data_store",
        actions=actions,
        before=before,
        after=after,
        replace_paths=(),
        tags={"env": "prod"},
        is_replace=False,
    )


def test_flags_database_with_final_snapshot_skipped() -> None:
    change = _database_change(
        actions=("update",),
        before={"skip_final_snapshot": False},
        after={"skip_final_snapshot": True},
    )

    findings = R003SkipFinalSnapshot().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "R003"
    assert findings[0].resource == change.address


def test_flags_deletion_using_before_state() -> None:
    change = _database_change(
        actions=("delete",),
        before={"skip_final_snapshot": True},
        after=None,
    )

    findings = R003SkipFinalSnapshot().check(change, [change])

    assert len(findings) == 1


def test_does_not_flag_database_retaining_final_snapshot() -> None:
    change = _database_change(
        actions=("update",),
        before={"skip_final_snapshot": True},
        after={"skip_final_snapshot": False},
    )

    assert R003SkipFinalSnapshot().check(change, [change]) == []
