"""Positive and negative checks for R004."""

from dataclasses import replace
from pathlib import Path

from argus.parse_plan import parse_plan
from argus.rules.r004 import R004PublicDatabasePort


_PLAN = Path(__file__).resolve().parents[2] / "fixtures" / "plans" / "act5_agent_landing_zone.json"


def test_flags_public_database_ingress_rule() -> None:
    change = parse_plan(_PLAN)[0]

    findings = R004PublicDatabasePort().check(change, [change])

    assert len(findings) == 1
    assert findings[0].rule_id == "R004"
    assert "1433" in findings[0].message


def test_does_not_flag_restricted_database_ingress_rule() -> None:
    change = parse_plan(_PLAN)[0]
    restricted = replace(
        change,
        after={**change.after, "cidr_blocks": ["10.0.0.0/8"]},
    )

    assert R004PublicDatabasePort().check(restricted, [restricted]) == []


def test_flags_inline_security_group_ingress() -> None:
    change = parse_plan(_PLAN)[0]
    group = replace(
        change,
        resource_type="aws_security_group",
        canonical_type="network_security_group",
        after={"ingress": [change.after]},
    )

    findings = R004PublicDatabasePort().check(group, [group])

    assert len(findings) == 1


def test_does_not_flag_public_egress() -> None:
    change = parse_plan(_PLAN)[0]
    egress = replace(change, after={**change.after, "type": "egress"})

    assert R004PublicDatabasePort().check(egress, [egress]) == []
