"""R007 checks SQL Server major upgrades against their parameter group."""

from pathlib import Path
from dataclasses import replace

from argus.parse_plan import parse_plan
from argus.rules.r007 import SqlServerMajorUpgradeParameterGroup


PLANS = Path(__file__).resolve().parents[2] / "fixtures" / "plans"


def test_major_upgrade_with_unchanged_parameter_group_triggers() -> None:
    changes = parse_plan(PLANS / "act2_major_upgrade.json")
    database = next(change for change in changes if change.address == "aws_db_instance.orders")

    findings = SqlServerMajorUpgradeParameterGroup().check(database, changes)

    assert len(findings) == 1
    assert findings[0].rule_id == "R007"
    assert findings[0].resource == database.address
    assert findings[0].severity == "high"
    assert findings[0].source_doc_ids == ("rds-sqlserver-upgrade-considerations",)
    assert "15.00 to 16.00" in findings[0].message
    assert "orders-sqlserver-se-15" in findings[0].message


def test_clean_change_does_not_trigger() -> None:
    changes = parse_plan(PLANS / "clean_change.json")

    assert all(
        SqlServerMajorUpgradeParameterGroup().check(change, changes) == []
        for change in changes
    )


def test_default_or_replaced_parameter_group_does_not_trigger() -> None:
    changes = parse_plan(PLANS / "act2_major_upgrade.json")
    database = next(change for change in changes if change.address == "aws_db_instance.orders")
    rule = SqlServerMajorUpgradeParameterGroup()
    default_group = replace(
        database,
        before={**database.before, "parameter_group_name": "default.sqlserver-se-15.0"},
        after={**database.after, "parameter_group_name": "default.sqlserver-se-15.0"},
    )
    new_group = replace(
        database,
        after={**database.after, "parameter_group_name": "orders-sqlserver-se-16"},
    )

    assert rule.check(default_group, (default_group,)) == []
    assert rule.check(new_group, (new_group,)) == []
