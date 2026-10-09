"""Synthetic positive and negative cases for G18."""

from argus.models import Change
from argus.rules.g18 import G18ProductionMultiAzDisabled


def _change(before: bool, after: bool, env: str = "prod") -> Change:
    return Change("aws_db_instance.sample", "aws_db_instance", "database_instance",
                  ("update",), {"multi_az": before}, {"multi_az": after},
                  (), {"env": env}, False)


def test_g18_flags_production_multi_az_shutdown() -> None:
    rule = G18ProductionMultiAzDisabled()
    change = _change(True, False)
    assert [item.rule_id for item in rule.check(change, (change,))] == ["G18"]


def test_g18_ignores_nonproduction_and_unchanged_multi_az() -> None:
    rule = G18ProductionMultiAzDisabled()
    for change in (_change(True, False, "dev"), _change(True, True),
                   _change(False, False)):
        assert rule.check(change, (change,)) == []
