"""Synthetic positive and negative cases for G15."""

from argus.models import Change
from argus.rules.g15 import G15GuardDutyDisabled


def _change(before: dict | None, after: dict | None, actions: tuple[str, ...]) -> Change:
    return Change("aws_guardduty_detector.sample", "aws_guardduty_detector",
                  "aws_guardduty_detector", actions, before, after, (), {}, False)


def test_g15_flags_disabled_or_deleted_detector() -> None:
    rule = G15GuardDutyDisabled()
    disabled = _change({"enable": True}, {"enable": False}, ("update",))
    deleted = _change({"enable": True}, None, ("delete",))
    assert [item.rule_id for item in rule.check(disabled, (disabled,))] == ["G15"]
    assert [item.rule_id for item in rule.check(deleted, (deleted,))] == ["G15"]


def test_g15_ignores_enabled_detector_and_other_resources() -> None:
    rule = G15GuardDutyDisabled()
    enabled = _change({"enable": True}, {"enable": True}, ("update",))
    unrelated = Change("aws_cloudwatch_log_group.sample", "aws_cloudwatch_log_group",
                       "aws_cloudwatch_log_group", ("update",), {}, {"enable": False},
                       (), {}, False)
    assert rule.check(enabled, (enabled,)) == []
    assert rule.check(unrelated, (unrelated,)) == []
