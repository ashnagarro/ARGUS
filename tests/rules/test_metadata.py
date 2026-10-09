"""Readable rule metadata keeps stable audit IDs across implementations."""

from dataclasses import asdict
from datetime import date
import json
import re

from argus.models import Change
from argus.rules import load_rules, resolve_rule_id
from argus.rules.r001 import StatefulReplacement
from argus.warden import apply_exceptions, check_agent_files


def test_all_existing_rules_have_generic_metadata_and_stable_ids() -> None:
    rules = load_rules(include_governance=True)
    assert [rule.id for rule in rules] == [
        *(f"G{number:02d}" for number in range(1, 27)), "G28", "G29",
        *(f"R{number:03d}" for number in range(1, 8)),
    ]
    assert len({rule.name for rule in rules}) == len(rules)
    for rule in rules:
        assert re.fullmatch(r"[a-z]+(?:-[a-z0-9]+)*", rule.name)
        assert rule.title and rule.title[0].isupper()
        assert rule.applies_to == ("terraform/aws",)
        assert not re.search(r"\b(?:terraform|aws|azure|bicep|cloudformation|rds)\b",
                             rule.name + " " + rule.title, re.IGNORECASE)

    by_id = {rule.id: rule for rule in rules}
    assert (by_id["R001"].name, by_id["R001"].title) == (
        "data-store-replacement", "Data store will be destroyed and recreated",
    )
    assert (by_id["R007"].name, by_id["R007"].title) == (
        "engine-config-incompatible-with-upgrade",
        "Engine configuration not compatible with the target major version",
    )
    assert by_id["G28"].name == "agent-sensitive-change-needs-approval"


def test_rule_lookup_accepts_audit_id_or_readable_name() -> None:
    assert resolve_rule_id("R001") == resolve_rule_id("data-store-replacement") == "R001"
    assert resolve_rule_id("g28") == resolve_rule_id("agent-sensitive-change-needs-approval") == "G28"
    assert resolve_rule_id("W001") == resolve_rule_id("agent-out-of-scope-change") == "W001"
    assert resolve_rule_id("missing-rule") is None


def test_finding_serialization_preserves_id_and_lists_applicable_implementation() -> None:
    change = Change(
        address="aws_db_instance.example", resource_type="aws_db_instance",
        canonical_type="data_store", actions=("delete", "create"),
        before={"identifier": "old"}, after={"identifier": "new"},
        replace_paths=(("identifier",),), tags={}, is_replace=True,
    )
    finding = StatefulReplacement().finding(change, "Identifier changes.")
    payload = json.loads(json.dumps(asdict(finding)))
    assert payload["rule_id"] == "R001"
    assert payload["name"] == "data-store-replacement"
    assert payload["title"] == "Data store will be destroyed and recreated"
    assert payload["applies_to"] == ["terraform/aws"]
    assert payload["source_tool"] == "terraform" and payload["cloud"] == "aws"


def test_warden_rule_name_can_waive_same_stable_id() -> None:
    (finding,) = check_agent_files("agent:test", ("infra/main.tf",), {"test": ("tests/**",)})
    assert finding.rule_id == "W001"
    assert finding.name == "agent-out-of-scope-change"
    assert finding.applies_to == ("agent/files",)
    (waived,) = apply_exceptions((finding,), ({
        "rule_id": "agent-out-of-scope-change", "resource": "infra/main.tf",
        "owner": "test", "reason": "reviewed", "ticket": "TEST-1", "expires": "2026-10-10",
    },), date(2026, 10, 9))
    assert waived.waived and waived.rule_id == "W001"
