"""Synthetic positive and negative cases for G20."""

from argus.models import Change
from argus.rules.g20 import G20BackupPlanRuleDeleted


def _change(before: list[dict], after: list[dict] | None) -> Change:
    return Change("aws_backup_plan.sample", "aws_backup_plan", "aws_backup_plan",
                  ("update",) if after is not None else ("delete",),
                  {"rule": before}, {"rule": after} if after is not None else None,
                  (), {}, False)


def test_g20_flags_removed_backup_rule() -> None:
    rule = G20BackupPlanRuleDeleted()
    change = _change([{"rule_name": "daily"}, {"rule_name": "weekly"}],
                     [{"rule_name": "daily"}])
    findings = rule.check(change, (change,))
    assert [item.rule_id for item in findings] == ["G20"]
    assert "weekly" in findings[0].message
    deleted = _change([{"rule_name": "daily"}], None)
    assert [item.rule_id for item in rule.check(deleted, (deleted,))] == ["G20"]


def test_g20_ignores_rule_retained_during_schedule_change() -> None:
    rule = G20BackupPlanRuleDeleted()
    change = _change([{"rule_name": "daily", "schedule": "old"}],
                     [{"rule_name": "daily", "schedule": "new"}])
    assert rule.check(change, (change,)) == []
