"""The optional governance pack is gated and produces a reproducible sweep."""

from __future__ import annotations

import json
from pathlib import Path

from argus import cli
from argus.governance import GovernanceContext
from argus.parse_plan import parse_plan
from argus.rules import load_rules, run_rules


ROOT = Path(__file__).resolve().parents[1]
SWEEP = ROOT / "fixtures" / "plans" / "act6_governance_sweep.json"


def _project(root: Path, *, enabled: bool) -> None:
    (root / "argus.toml").write_text(
        f"[flags]\ngovernance_pack = {'true' if enabled else 'false'}\n",
        encoding="utf-8",
    )
    for name in ("permissions.yaml", "exceptions.yaml", "controls.yaml"):
        (root / name).write_bytes((ROOT / name).read_bytes())


def test_governance_flag_gates_28_rules_and_act6_has_many_distinct_violations(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert all(not rule.id.startswith("G") for rule in load_rules())
    governance = [rule for rule in load_rules(include_governance=True,
                   controls_path=ROOT / "controls.yaml") if rule.id.startswith("G")]
    assert len(governance) == 28
    assert all(rule.controls for rule in governance)

    _project(tmp_path, enabled=False)
    # Existing sensitive-resource permission checks still require a human.
    assert cli.run_check(SWEEP) == 2
    disabled = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert disabled["rule_findings"] == []
    capsys.readouterr()

    _project(tmp_path, enabled=True)
    assert cli.run_check(SWEEP) == 1
    active = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    ids = {finding["rule_id"] for finding in active["rule_findings"]}
    assert len(ids) >= 10
    assert {"G01", "G03", "G08", "G12", "G20", "G24"} <= ids
    assert all(finding["controls"] for finding in active["rule_findings"])
    assert "G17" not in ids  # The organization has not set a retention minimum.


def test_configured_thresholds_and_ticket_change_context_findings() -> None:
    changes = parse_plan(SWEEP)
    context = GovernanceContext(
        required_tags=("env", "owner"), approved_regions=("synthetic-east",),
        allowed_instance_classes=("db.synthetic.small",), minimum_retention_days=10,
        ticket="SYNTH-1",
    )
    findings = run_rules(changes, include_governance=True,
                         governance_context=context, controls_path=ROOT / "controls.yaml")
    ids = {finding.rule_id for finding in findings}
    assert {"G17", "G21", "G22", "G23"} <= ids
    assert "G24" not in ids


def test_cli_tf_file_scan_reports_secret_without_recording_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    _project(tmp_path, enabled=True)
    source = tmp_path / "synthetic.tf"
    source.write_text('password = "synthetic-placeholder"\n', encoding="utf-8")
    plan = ROOT / "fixtures" / "plans" / "clean_change.json"
    assert cli.main(["check", str(plan), "--tf-file", str(source), "--ticket", "SYNTH-1"]) == 1
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert any(item["rule_id"] == "G26" for item in record["rule_findings"])
    assert "synthetic-placeholder" not in json.dumps(record)
