"""R001 catches stateful replacements and names the replacement cause."""

from pathlib import Path
from dataclasses import replace

from argus.parse_plan import parse_plan
from argus.rules.r001 import StatefulReplacement


PLANS = Path(__file__).resolve().parents[2] / "fixtures" / "plans"


def test_replaced_database_triggers() -> None:
    change = parse_plan(PLANS / "act1_replace_pii_db.json")[0]

    findings = StatefulReplacement().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "R001"
    assert findings[0].severity == "critical"
    assert findings[0].resource == "aws_db_instance.orders"
    assert "identifier" in findings[0].message


def test_tag_only_change_does_not_trigger() -> None:
    change = parse_plan(PLANS / "clean_change.json")[0]

    assert StatefulReplacement().check(change, [change]) == []


def test_replacement_requires_canonical_data_store_type() -> None:
    change = parse_plan(PLANS / "act1_replace_pii_db.json")[0]
    unrelated = replace(change, canonical_type="compute_instance")

    assert StatefulReplacement().check(unrelated, [unrelated]) == []


def test_volume_replacement_uses_same_data_store_rule() -> None:
    plan = {"resource_changes": [{
        "address": "aws_ebs_volume.synthetic", "type": "aws_ebs_volume",
        "change": {"actions": ["delete", "create"], "before": {}, "after": {},
                   "replace_paths": [["availability_zone"]]},
    }]}
    change = parse_plan(plan)[0]

    findings = StatefulReplacement().check(change, [change])

    assert change.canonical_type == "data_store"
    assert len(findings) == 1
    assert "availability_zone" in findings[0].message
