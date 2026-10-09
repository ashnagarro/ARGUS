"""Phase 8 agent scope, approvals, ledger, and expiring exceptions."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from argus import cli
from argus.report import Report, render_terminal
from argus.verdict import decide_verdict
from argus.warden import apply_exceptions, check_agent_files, load_agents, load_exceptions


ROOT = Path(__file__).resolve().parents[1]


def test_agent_scope_and_waiver_dates(tmp_path: Path) -> None:
    agents_path = tmp_path / "agents.yaml"
    agents_path.write_text(
        "agents:\n  smith:\n    - argus/rules/**\n    - tests/rules/**\n",
        encoding="utf-8",
    )
    agents = load_agents(agents_path)
    assert check_agent_files("agent:smith", ["argus/rules/r008.py"], agents) == ()
    findings = check_agent_files("agent:smith", ["infra/main.tf"], agents)
    assert len(findings) == 1
    assert findings[0].severity == "critical"
    assert decide_verdict(findings) == "NO-GO"

    exceptions_path = tmp_path / "exceptions.yaml"
    exceptions_path.write_text(
        "exceptions:\n"
        "  - rule_id: W001\n"
        "    resource: infra/main.tf\n"
        "    owner: test-owner\n"
        "    reason: approved migration\n"
        "    ticket: TEST-42\n"
        "    expires: 2026-10-10\n",
        encoding="utf-8",
    )
    exceptions = load_exceptions(exceptions_path)
    active = apply_exceptions(findings, exceptions, date(2026, 10, 9))
    assert active[0].waived is True
    assert decide_verdict(active) == "GO"
    report = Report("GO", "2026-10-09T00:00:00Z", 0.0, 0,
                    active, (), (), ())
    assert "WAIVED until 2026-10-10" in render_terminal(report)
    expired = apply_exceptions(findings, exceptions, date(2026, 10, 11))
    assert expired[0].waived is False
    assert "exception expired on 2026-10-10" in expired[0].message.lower()
    assert decide_verdict(expired) == "NO-GO"


def test_agent_check_logs_permission_and_scope_in_test_workspace(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    for name in ("agents.yaml", "permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    plan = ROOT / "fixtures" / "plans" / "clean_change.json"
    assert cli.run_check(
        plan, tmp_path / "reports", author="agent:smith",
        changed_files=("argus/rules/r008.py",),
    ) == 2
    output = capsys.readouterr().out
    assert "Verdict: NEEDS HUMAN" in output
    assert "Human approval required" in output
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    run_id = record["run_id"]
    assert record["rule_findings"] == []
    trace = (tmp_path / "ledger" / "traces" / f"{run_id}.jsonl").read_text(encoding="utf-8")
    assert '"action": "agent_change"' in trace
    ledger = (tmp_path / "ledger" / "ledger.jsonl").read_text(encoding="utf-8")
    assert '"author": "agent:smith"' in ledger
    assert '"input_hash":' in ledger

    assert cli.run_check(
        plan, tmp_path / "reports", author="agent:smith",
        changed_files=("infra/main.tf",),
    ) == 1
    assert "W001 [critical]" in capsys.readouterr().out


def test_sensitive_resource_needs_approval_even_for_allowed_agent_file(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    for name in ("agents.yaml", "permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    plan = ROOT / "fixtures" / "plans" / "act5_agent_landing_zone.json"
    cli.run_check(plan, tmp_path / "reports", author="agent:landing-zone",
                  changed_files=("infra/landing-zone/network.tf",))
    output = capsys.readouterr().out
    assert "Approval required to review aws_security_group_rule.database_ingress" in output
    assert "Human approval required for agent change" in output
    assert "W001" not in output
