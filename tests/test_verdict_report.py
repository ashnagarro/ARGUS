"""Phase 4 verdict, report, and command-line checks."""

from pathlib import Path
import subprocess
import sys

import pytest

from argus.models import AIFinding, RuleFinding
from argus.report import Report, render_html, render_markdown
from argus.verdict import decide_verdict, merge_conditions


ROOT = Path(__file__).resolve().parents[1]
PLANS = ROOT / "fixtures" / "plans"


def rule_finding(severity: str = "critical") -> RuleFinding:
    return RuleFinding(
        rule_id="R001",
        resource="aws_db_instance.synthetic",
        title="Stateful resource replacement",
        severity=severity,
        message="identifier causes replacement",
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
    assert "Resolve R001" in merge_conditions(findings)[0]


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


@pytest.mark.parametrize(
    ("fixture", "expected_status", "expected_verdict"),
    [
        ("act1_replace_pii_db.json", 1, "NO-GO"),
        ("clean_change.json", 0, "GO"),
    ],
)
def test_check_command_writes_reports(
    fixture: str, expected_status: int, expected_verdict: str, tmp_path: Path
) -> None:
    report_dir = tmp_path / "reports"
    result = subprocess.run(
        [sys.executable, "-m", "argus", "check", str(PLANS / fixture),
         "--report-dir", str(report_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected_status, result.stderr
    assert expected_verdict in result.stdout
    assert expected_verdict in (report_dir / "latest.md").read_text(encoding="utf-8")
    assert expected_verdict in (report_dir / "latest.html").read_text(encoding="utf-8")
