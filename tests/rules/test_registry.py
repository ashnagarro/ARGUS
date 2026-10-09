"""Phase 3 discovers every deterministic rule automatically."""

from argus.rules import load_rules


def test_all_phase_three_rules_are_loaded() -> None:
    assert [rule.id for rule in load_rules()][:6] == [
        "R001", "R002", "R003", "R004", "R005", "R006"
    ]
