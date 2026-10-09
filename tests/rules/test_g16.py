"""Synthetic positive and negative cases for G16."""

from argus.models import Change
from argus.rules.g16 import G16ConfigRecorderStopped


def _change(before: dict | None, after: dict | None, actions: tuple[str, ...]) -> Change:
    return Change("aws_config_configuration_recorder_status.sample",
                  "aws_config_configuration_recorder_status",
                  "aws_config_configuration_recorder_status", actions,
                  before, after, (), {}, False)


def test_g16_flags_stopped_or_deleted_status() -> None:
    rule = G16ConfigRecorderStopped()
    stopped = _change({"is_enabled": True}, {"is_enabled": False}, ("update",))
    deleted = _change({"is_enabled": True}, None, ("delete",))
    assert [item.rule_id for item in rule.check(stopped, (stopped,))] == ["G16"]
    assert [item.rule_id for item in rule.check(deleted, (deleted,))] == ["G16"]


def test_g16_ignores_running_recorder() -> None:
    rule = G16ConfigRecorderStopped()
    running = _change({"is_enabled": False}, {"is_enabled": True}, ("update",))
    assert rule.check(running, (running,)) == []
