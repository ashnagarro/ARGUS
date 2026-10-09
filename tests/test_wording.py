"""Verdict labels and human approval summaries remain readable."""

import json
from pathlib import Path
import re

from argus import cli
from argus.report import Report, render_html, render_markdown, render_terminal
from argus.web import result_page


ROOT = Path(__file__).resolve().parents[1]


def test_no_go_labels_fixes_across_report_and_web():
    report = Report(verdict="NO-GO", run_at="2026-10-09T00:00:00Z",
                    elapsed_seconds=0, ai_calls=0, rule_findings=(), ai_findings=(),
                    conditions=("Fix access",))
    for output in (render_terminal(report), render_markdown(report), render_html(report),
                   result_page({"verdict": "NO-GO", "conditions": ["Fix access"]}).decode()):
        assert "Required fixes before merge" in output
    assert "Conditions to merge" not in render_terminal(report)


def test_human_sensitive_approvals_are_grouped_but_agent_approvals_are_specific(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    plan = ROOT / "fixtures" / "plans" / "real_risky_plan.json"
    cli.run_check(plan, emit_output=False, governance_enabled=False, team_enabled=False)
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text())
    approval_lines = [item for item in record["ask_you"] if item.startswith("Approval required to review")]
    assert len(approval_lines) == 1
    assert re.search(r"\d+ sensitive resources? \(", approval_lines[0])
    assert "aws_security_group_rule" in approval_lines[0]
    assert "aws_iam_policy" in approval_lines[0]

    agent_plan = ROOT / "fixtures" / "plans" / "act5_agent_landing_zone.json"
    (tmp_path / "agents.yaml").write_bytes((ROOT / "agents.yaml").read_bytes())
    cli.run_check(agent_plan, author="agent:landing-zone",
                  changed_files=("infra/landing-zone/network.tf",),
                  emit_output=False, governance_enabled=False, team_enabled=False)
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text())
    assert any("aws_security_group_rule.database_ingress" in item for item in record["ask_you"])
