"""Console renders saved runs offline and never exposes environment values."""

from __future__ import annotations

import json
from pathlib import Path

from argus import cli
from argus.console import _findings, write_console


ROOT = Path(__file__).resolve().parents[1]


def test_console_backfills_legacy_warden_title_and_name() -> None:
    html = _findings({"rule_findings": [{
        "rule_id": "W001", "resource": "infra/other/main.tf",
        "title": "Agent file outside allowed scope",
        "message": "Agent synthetic changed a file outside scope.",
    }]}, {})
    title = "Agent changed files outside its permitted scope"
    detail = "Resource: infra/other/main.tf · Tool: agent · Cloud: n/a · Trigger:"
    label = "(W001 · agent-out-of-scope-change)"
    assert html.index(title) < html.index(detail) < html.index(label)


def test_console_is_self_contained_and_redacts_secrets(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-console-key")
    monkeypatch.setenv("ARGUS_TEST_SECRET", "UniqueConsoleEnvironmentValue123")
    runs = tmp_path / "ledger" / "runs"
    traces = tmp_path / "ledger" / "traces"
    runs.mkdir(parents=True)
    traces.mkdir()
    (tmp_path / "ledger" / "ledger.jsonl").write_text(
        json.dumps({"type": "compile", "status": "compiled", "rule_id": "R007",
                    "finding_ids": ["F1"]}) + "\n", encoding="utf-8",
    )
    (runs / "saved-run.json").write_text(json.dumps({
        "run_id": "saved-run", "run_at": "2026-10-09T00:00:00+00:00",
        "plan": "C:\\synthetic\\act2.json", "verdict": "GO-WITH-CONDITIONS",
        "author": "agent:smith", "ai_calls": 3, "elapsed_seconds": 4.5,
        "rule_findings": [{
            "rule_id": "R001", "resource": "aws_db_instance.orders",
            "title": "Stateful resource replacement",
            "headline": "Production database will be deleted and recreated",
            "message": "identifier causes replacement", "severity": "critical",
            "waived": True,
        }],
        "ai_findings": [{"id": "F1", "resource": "aws_db_instance.orders",
                         "claim": "Use sk-test-console-key and UniqueConsoleEnvironmentValue123",
                         "recommended_action": "Choose a new group.", "verified": True,
                         "evidence": [{"doc_id": "synthetic-doc", "quote": "A new group is required.",
                                       "url": "https://docs.example.test/group",
                                       "retrieved_at": "2026-10-09"}]}],
        "conditions": ["Choose a new group."], "trace_steps": ["searched corpus"],
    }), encoding="utf-8")
    (traces / "saved-run.jsonl").write_text(
        json.dumps({"event": "permission_decision", "action": "search_corpus",
                    "resource": "aws_db_instance.orders", "decision": "auto",
                    "reason": "read-only tool"}) + "\n"
        + json.dumps({"event": "tool_result", "step": "read synthetic-doc section 2"}) + "\n",
        encoding="utf-8",
    )
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "rds-sqlserver-upgrade-considerations.md").write_bytes(
        (ROOT / "corpus" / "rds-sqlserver-upgrade-considerations.md").read_bytes()
    )
    test_path = tmp_path / "tests" / "rules" / "test_r007.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("# verified by Smith at compile\n", encoding="utf-8")
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "act3_baseline.json").write_text(
        json.dumps({"ai_calls": 13, "elapsed_seconds": 42.51}), encoding="utf-8",
    )

    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.main(["console"]) == 0
    assert "Console:" in capsys.readouterr().out
    html = (tmp_path / "reports" / "console.html").read_text(encoding="utf-8")
    assert "sk-" not in html.lower()
    assert "sk-test-console-key" not in html
    assert "UniqueConsoleEnvironmentValue123" not in html
    assert "ARGUS Console" in html
    assert "2026-10-09 05:30:00 IST" in html
    assert "GO-WITH-CONDITIONS" in html
    title = "Data store will be destroyed and recreated"
    detail = "Resource: aws_db_instance.orders · Tool: terraform · Cloud: aws · Trigger:"
    label = "(R001 · data-store-replacement)"
    assert html.index(title) < html.index(detail) < html.index(label)
    assert f'<small class="rule-ref">{label}</small>' in html
    assert "agent:smith" in html
    assert "A new group is required." in html
    assert 'href="https://docs.example.test/group"' in html
    assert "retrieved 2026-10-09" in html
    assert "Permission: search_corpus" in html
    assert "Agentic-loop timeline" in html
    assert "Learned rules library" in html
    assert "passed at compile" in html
    assert "13 calls / 42.51 s" in html
    assert "Works now" in html and "Prototype / roadmap" in html
    assert "<style>" in html and "<script>" in html
    assert "<script src=" not in html

    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url) or True)
    assert cli.main(["console", "--open"]) == 0
    assert len(opened) == 1 and opened[0].endswith("/reports/console.html")
