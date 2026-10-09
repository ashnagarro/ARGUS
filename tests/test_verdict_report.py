"""Phase 4 verdict, report, and command-line checks."""

from pathlib import Path

import pytest

from argus import cli
from argus.models import AIFinding, RuleFinding
from argus.report import Report, render_html, render_markdown, render_terminal
from argus.verdict import decide_verdict, merge_conditions


ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "fixtures" / "plans"


def rule_finding(severity: str = "critical") -> RuleFinding:
    return RuleFinding(
        rule_id="R001",
        resource="aws_db_instance.synthetic",
        name="data-store-replacement",
        title="Data store will be destroyed and recreated",
        severity=severity,
        message="identifier causes replacement",
        headline="Production data store will be deleted and recreated",
        source_tool="terraform",
        cloud="aws",
    )


def ai_finding(verified: bool, claim: str = "A sourced concern") -> AIFinding:
    return AIFinding(
        id="AI-001",
        resource="aws_db_instance.synthetic",
        claim=claim,
        severity="medium",
        recommended_action="Review the parameter group before merge.",
        verified=verified,
    )


def test_high_or_critical_rule_blocks_even_with_verified_ai() -> None:
    findings = (rule_finding(),)
    assert decide_verdict(findings, (ai_finding(True),)) == "NO-GO"
    assert merge_conditions(findings)[0] == "identifier causes replacement"


def test_verified_ai_adds_a_condition() -> None:
    findings = (ai_finding(True),)
    assert decide_verdict((), findings) == "GO-WITH-CONDITIONS"
    assert merge_conditions((), findings) == ("Review the parameter group before merge.",)


def test_unverified_ai_never_changes_verdict() -> None:
    assert decide_verdict((), (ai_finding(False),)) == "GO"
    assert merge_conditions((), (ai_finding(False),)) == ()


def test_reports_group_findings_and_escape_html() -> None:
    report = Report(
        verdict="NO-GO",
        run_at="2026-10-09T00:00:00+00:00",
        elapsed_seconds=1.25,
        ai_calls=1,
        rule_findings=(rule_finding(),),
        ai_findings=(ai_finding(True), ai_finding(False, "<unsafe>")),
        conditions=("Resolve R001",),
        trace_steps=("searched corpus", "read section",),
        ask_you=("Review UNVERIFIED finding",),
    )

    markdown = render_markdown(report)
    html = render_html(report)

    for section in ("RULE", "AI VERIFIED", "AI UNVERIFIED"):
        assert section in markdown
        assert section in html
    assert "Run: python -m argus compile AI-001 to make this a rule" in markdown
    assert "- Step 1: searched corpus" in markdown
    assert "- Step 2: read section" in markdown
    assert "&lt;unsafe&gt;" in markdown
    assert "<unsafe>" not in markdown
    assert "Review UNVERIFIED finding" in markdown
    assert "&lt;unsafe&gt;" in html
    assert "<unsafe>" not in html
    title = "Data store will be destroyed and recreated"
    label = "(R001 · data-store-replacement)"
    for rendered in (render_terminal(report), markdown, html):
        assert (rendered.index(title) < rendered.index("Resource:") <
                rendered.index("Tool: terraform") < rendered.index("Cloud: aws") <
                rendered.index("Trigger:") < rendered.index(label))
    assert "<small>(R001 · data-store-replacement)</small>" in markdown
    assert '<small class="rule-ref">(R001 · data-store-replacement)</small>' in html


def test_offline_replay_reports_original_live_run_instead_of_bare_zero() -> None:
    report = Report(
        verdict="GO-WITH-CONDITIONS", run_at="2026-10-09T00:00:00+00:00",
        elapsed_seconds=0.15, ai_calls=0, rule_findings=(), ai_findings=(),
        conditions=(), replayed_from_run_id="synthetic-live",
        original_ai_calls=4, original_elapsed_seconds=12.34,
    )
    expected = "replayed (offline) - original live run: 4 AI calls, 12.34 s"
    assert expected in render_terminal(report)
    assert expected in render_markdown(report)
    assert expected in render_html(report)


@pytest.mark.parametrize(
    ("fixture", "expected_status", "expected_verdict"),
    [
        ("act1_replace_pii_db.json", 1, "NO-GO"),
        ("clean_change.json", 0, "GO"),
    ],
)
def test_check_command_writes_reports(
    fixture: str, expected_status: int, expected_verdict: str, tmp_path: Path,
    monkeypatch, capsys,
) -> None:
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    for name in ("permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    assert cli.main(["check", str(PLANS / fixture),
                     "--report-dir", str(report_dir)]) == expected_status
    assert expected_verdict in capsys.readouterr().out
    assert expected_verdict in (report_dir / "latest.md").read_text(encoding="utf-8")
    assert expected_verdict in (report_dir / "latest.html").read_text(encoding="utf-8")
