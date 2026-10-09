"""Phase 9B report polish and verified-answer stopping."""

from __future__ import annotations

from pathlib import Path

from argus import scholar
from argus.agent_loop import AgentLoopResult
from argus.models import AIFinding
from argus.parse_plan import parse_plan
from argus.report import ADVISORY_NOTICE, Report, render_html, render_markdown, render_terminal
from argus.rules import run_rules
from argus.verdict import merge_conditions


ROOT = Path(__file__).resolve().parents[1]


def test_rule_advice_tags_and_learned_provenance_appear_in_reports() -> None:
    act1 = run_rules(parse_plan(ROOT / "fixtures" / "plans" / "act1_replace_pii_db.json"))
    r001 = next(item for item in act1 if item.rule_id == "R001")
    assert r001.headline == "Production database holding PII will be deleted and recreated"
    assert r001.tags and r001.tags["env"] == "prod"
    assert merge_conditions((r001,)) == (r001.how_to_fix,)
    assert "prevent_destroy = true" in r001.how_to_fix

    act3 = run_rules(parse_plan(ROOT / "fixtures" / "plans" / "act3_major_upgrade_second.json"))
    r007 = next(item for item in act3 if item.rule_id == "R007")
    report = Report("NO-GO", "2026-10-09T00:00:00+00:00", 0.0, 0,
                    (r007,), (), (r007.how_to_fix,))
    expected = ("Learned rule R007 - compiled from AI finding F1, "
                "human-approved on 2026-10-09 - now ENFORCED")
    assert expected in render_terminal(report)
    assert expected in render_markdown(report)
    assert expected in render_html(report)


def test_projector_html_uses_local_time_and_hides_empty_sections() -> None:
    empty = Report("GO", "2026-10-09T00:00:00+00:00", 0.0, 0, (), (), ())
    html = render_html(empty)
    assert 'class="banner go"' in html
    assert "font-size:3rem" in html
    assert "2026-10-09 05:30:00 IST" in html
    assert "<h2>RULE</h2>" not in html
    assert "<h2>AI VERIFIED</h2>" not in html
    assert "<h2>Ask you</h2><p>None.</p>" in html

    ai = AIFinding("F1", "aws_db_instance.orders", "Synthetic advice", "high",
                   "Use a matching group.", True)
    report = Report("GO-WITH-CONDITIONS", "2026-10-09T00:00:00+00:00",
                    0.0, 1, (), (ai,), ())
    assert ADVISORY_NOTICE in render_terminal(report)
    assert ADVISORY_NOTICE in render_html(report)
    assert 'class="banner conditions"' in render_html(report)


def test_scholar_stops_after_first_verified_answer(tmp_path: Path, monkeypatch) -> None:
    changes = parse_plan(ROOT / "fixtures" / "plans" / "act2_major_upgrade.json")
    calls: list[str] = []

    def fake_loop(change, *args, **kwargs):
        calls.append(change.address)
        return AgentLoopResult("complete", {"findings": [{}]}, 1, 0, 0.1,
                               (), (), ())

    monkeypatch.setattr(scholar, "run_agent_loop", fake_loop)
    monkeypatch.setattr(scholar, "_as_findings", lambda payload, change, documents: (
        AIFinding("F1", change.address, "Verified advice", "high", "Fix it.", True),
    ))
    result = scholar.research_changes(
        changes, (), documents={}, live=True, client=object(),
        cache_dir=tmp_path / "cache", trace_dir=tmp_path / "traces",
        permissions_path=ROOT / "permissions.yaml",
        schema_path=ROOT / "schemas" / "finding.schema.json",
    )
    assert result.status == "complete"
    assert result.ai_calls == 1
    assert calls == ["aws_db_instance.orders"]
    assert "verified_answer_stop" in (tmp_path / "traces" / f"{result.run_id}.jsonl").read_text(encoding="utf-8")
