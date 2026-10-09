"""Synthetic positive and negative cases for G17."""

import pytest

from argus.models import Change
from argus.rules.g17 import G17LogRetentionBelowMinimum


def _change(days: int | str) -> Change:
    return Change("aws_cloudwatch_log_group.sample", "aws_cloudwatch_log_group",
                  "aws_cloudwatch_log_group", ("update",),
                  {"retention_in_days": 30}, {"retention_in_days": days}, (), {}, False)


def test_g17_flags_retention_below_configured_minimum() -> None:
    rule = G17LogRetentionBelowMinimum(minimum_retention_days=30)
    change = _change(7)
    findings = rule.check(change, (change,))
    assert [item.rule_id for item in findings] == ["G17"]
    assert "configured 30-day minimum" in findings[0].message


def test_g17_ignores_indefinite_or_sufficient_retention_and_missing_policy() -> None:
    rule = G17LogRetentionBelowMinimum(minimum_retention_days=30)
    for days in (0, 30, 60, "7"):
        change = _change(days)
        assert rule.check(change, (change,)) == []
    assert G17LogRetentionBelowMinimum().check(_change(7), ()) == []
    with pytest.raises(ValueError):
        G17LogRetentionBelowMinimum(minimum_retention_days=0)
