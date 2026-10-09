"""Phase 2 tests for fake Terraform plans and adapter selection."""

from pathlib import Path

import pytest

from argus.parse_plan import parse_plan


PLANS = Path(__file__).resolve().parents[1] / "fixtures" / "plans"


def test_act1_replaces_a_tagged_database() -> None:
    changes = parse_plan(PLANS / "act1_replace_pii_db.json")

    assert len(changes) == 1
    change = changes[0]
    assert change.address == "aws_db_instance.orders"
    assert change.resource_type == "aws_db_instance"
    assert change.canonical_type == "database_instance"
    assert change.source_tool == "terraform"
    assert change.actions == ("delete", "create")
    assert change.is_replace
    assert change.replace_paths == (("identifier",),)
    assert change.tags["env"] == "prod"
    assert change.tags["data_classification"] == "pii-ssn"
    assert change.before["identifier"] != change.after["identifier"]


def test_act2_major_upgrade_keeps_old_parameter_group() -> None:
    changes = parse_plan(PLANS / "act2_major_upgrade.json")

    db = next(change for change in changes if change.address == "aws_db_instance.orders")
    group = next(change for change in changes if change.address == "aws_db_parameter_group.orders")
    assert db.before["engine_version"] == "15.00"
    assert db.after["engine_version"] == "16.00"
    assert db.after["allow_major_version_upgrade"] is True
    assert db.before["parameter_group_name"] == db.after["parameter_group_name"]
    assert group.after["family"] == "sqlserver-se-15.0"
    assert not db.is_replace


def test_act3_repeats_upgrade_mistake_on_billing() -> None:
    changes = parse_plan(PLANS / "act3_major_upgrade_second.json")

    db = next(change for change in changes if change.address == "aws_db_instance.billing")
    assert db.before["engine_version"] == "15.00"
    assert db.after["engine_version"] == "16.00"
    assert db.after["allow_major_version_upgrade"] is True
    assert db.before["parameter_group_name"] == db.after["parameter_group_name"]
    assert not db.is_replace


def test_act5_opens_database_port_to_internet() -> None:
    changes = parse_plan(PLANS / "act5_agent_landing_zone.json")

    assert len(changes) == 1
    rule = changes[0]
    assert rule.resource_type == "aws_security_group_rule"
    assert rule.after["from_port"] == 1433
    assert rule.after["to_port"] == 1433
    assert "0.0.0.0/0" in rule.after["cidr_blocks"]


def test_clean_change_updates_tags_only() -> None:
    changes = parse_plan(PLANS / "clean_change.json")

    assert len(changes) == 1
    change = changes[0]
    assert change.actions == ("update",)
    assert not change.is_replace
    assert change.before["tags"] != change.after["tags"]
    assert change.tags == change.after["tags"]


def test_removed_tags_are_not_inherited_from_prior_state() -> None:
    plan = {"resource_changes": [{
        "address": "aws_db_instance.synthetic", "type": "aws_db_instance",
        "change": {"actions": ["update"],
                   "before": {"tags": {"env": "prod", "owner": "synthetic-team"}},
                   "after": {"tags": {"env": "dev"}}},
    }]}
    change = parse_plan(plan)[0]
    assert change.tags == {"env": "dev"}


def test_unknown_adapter_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported plan source tool"):
        parse_plan({}, source_tool="unknown")
