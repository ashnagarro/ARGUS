"""Readable rule references preserve stable audit IDs."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
import json
from pathlib import Path

from argus import cli, mcp_server, smith
from argus.models import AIFinding
from argus.parse_plan import parse_plan
from argus.rules import run_rules
from argus.warden import apply_exceptions, load_exceptions


ROOT = Path(__file__).resolve().parents[1]
ACT1 = ROOT / "fixtures" / "plans" / "act1_replace_pii_db.json"


def _isolated_project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)
    for name in ("permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    plan = tmp_path / "act1.json"
    plan.write_bytes(ACT1.read_bytes())
    return plan


def test_disable_rule_accepts_name_and_records_id(tmp_path: Path, monkeypatch) -> None:
    plan = _isolated_project(tmp_path, monkeypatch)
    cli.run_check(plan, disabled_rules=("data-store-replacement",),
                  run_id="namedrule", write_artifacts=False, emit_output=False)
    record = json.loads((tmp_path / "ledger" / "runs" / "namedrule.json").read_text(encoding="utf-8"))
    assert record["disabled_rules"] == ["R001"]
    assert all(item["rule_id"] != "R001" for item in record["rule_findings"])


def test_exception_accepts_name_but_keeps_finding_id(tmp_path: Path) -> None:
    finding = next(item for item in run_rules(parse_plan(ACT1)) if item.rule_id == "R001")
    path = tmp_path / "exceptions.yaml"
    path.write_text(
        "exceptions:\n"
        "  - rule_id: data-store-replacement\n"
        f"    resource: {finding.resource}\n"
        "    owner: synthetic-team\n"
        "    reason: Test waiver\n"
        "    ticket: SYN-1\n"
        "    expires: 2026-10-31\n",
        encoding="utf-8",
    )
    waived = apply_exceptions((finding,), load_exceptions(path), date(2026, 10, 9))[0]
    assert waived.waived
    assert waived.rule_id == "R001"
    assert waived.name == "data-store-replacement"


def test_mcp_title_first_and_explain_accepts_name(tmp_path: Path, monkeypatch) -> None:
    _isolated_project(tmp_path, monkeypatch)
    (tmp_path / "fixtures" / "plans").mkdir(parents=True)
    (tmp_path / "fixtures" / "plans" / "act1.json").write_bytes(ACT1.read_bytes())
    outcome = mcp_server.argus_check("fixtures/plans/act1.json")
    finding = next(item for item in outcome["findings"] if item.get("rule_id") == "R001")
    assert list(finding)[:3] == ["title", "detail", "reference"]
    assert finding["title"] == "Data store will be destroyed and recreated"
    assert finding["reference"] == "(R001 · data-store-replacement)"
    assert finding["applies_to"] == ["terraform/aws"] or finding["applies_to"] == ("terraform/aws",)
    explanation = mcp_server.argus_explain("data-store-replacement")
    assert list(explanation)[:3] == ["title", "detail", "reference"]
    assert explanation["finding_id"] == "R001"


def test_compile_accepts_saved_finding_name(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    finding = AIFinding(
        id="AI-SYNTHETIC", resource="aws_db_instance.orders",
        claim="Synthetic configuration risk", severity="medium",
        recommended_action="Use a compatible configuration.", verified=True,
        evidence=(),
    )
    runs = tmp_path / "ledger" / "runs"
    runs.mkdir(parents=True)
    (runs / "one.json").write_text(json.dumps({
        "run_id": "one", "ai_findings": [{**asdict(finding), "name": "synthetic-config-risk"}],
    }), encoding="utf-8")
    seen = []

    def fake_compile(selected, root, **kwargs):
        seen.append(selected.id)
        return smith.CompileResult(
            status="compiled", finding_id=selected.id, rule_id="R999",
            attempts=1, reason=None, trace_path=tmp_path / "trace.jsonl",
        )

    monkeypatch.setattr(smith, "compile_finding", fake_compile)
    assert cli.run_compile("synthetic-config-risk") == 0
    assert seen == ["AI-SYNTHETIC"]


def test_compile_accepts_existing_rule_id_or_name(capsys) -> None:
    assert cli.run_compile("R001") == 0
    assert cli.run_compile("data-store-replacement") == 0
    assert capsys.readouterr().out.count("already compiled") == 2
