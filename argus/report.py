"""Render human-readable ARGUS decisions without external assets."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import re

from .models import AIFinding, RuleFinding


@dataclass(frozen=True, slots=True)
class Report:
    """The information shown to a human after one ARGUS run."""

    verdict: str
    run_at: str
    elapsed_seconds: float
    ai_calls: int
    rule_findings: tuple[RuleFinding, ...]
    ai_findings: tuple[AIFinding, ...]
    conditions: tuple[str, ...]
    trace_steps: tuple[str, ...] = ()
    ask_you: tuple[str, ...] = ()


def _single_line(value: str) -> str:
    return " ".join(value.split())

def _markdown_text(value: str) -> str:
    """Keep untrusted text literal in the Markdown report."""
    safe = escape(_single_line(value), quote=False)
    return re.sub(r"([\\`*_\[\]])", r"\\\1", safe)


def _rule_summary(report: Report) -> str:
    ids = sorted({finding.rule_id for finding in report.rule_findings})
    return f"{len(ids)} ({', '.join(ids)})" if ids else "0"


def _ai_groups(report: Report) -> tuple[tuple[AIFinding, ...], tuple[AIFinding, ...]]:
    verified = tuple(finding for finding in report.ai_findings if finding.verified)
    unverified = tuple(finding for finding in report.ai_findings if not finding.verified)
    return verified, unverified


def _ask_items(report: Report) -> tuple[str, ...]:
    items = list(report.ask_you)
    for finding in report.ai_findings:
        if not finding.verified:
            reason = finding.verification_reason or "evidence could not be verified"
            item = f"Review UNVERIFIED finding {finding.id}: {reason}."
            if item not in items:
                items.append(item)
    return tuple(items)


def _compile_hint(finding: AIFinding) -> str:
    return f"Run: python -m argus compile {finding.id} to make this a rule"


def _evidence_lines(finding: AIFinding) -> list[str]:
    lines: list[str] = []
    for item in finding.evidence:
        doc_id = _single_line(item.get("doc_id", "unknown document"))
        quote = _single_line(item.get("quote", ""))
        source = _single_line(item.get("url", ""))
        retrieved = _single_line(item.get("retrieved_at", ""))
        lines.append(f"{doc_id}: {quote}")
        if source:
            lines.append(f"Source: {source}")
        if retrieved:
            lines.append(f"Retrieved: {retrieved}")
    return lines


def render_terminal(report: Report) -> str:
    """Render a plain-text report for console output."""
    verified, unverified = _ai_groups(report)
    lines = [
        "ARGUS report",
        f"Verdict: {_single_line(report.verdict)}",
        f"Run at: {_single_line(report.run_at)}",
        f"Elapsed: {report.elapsed_seconds:.2f} seconds",
        f"AI calls: {report.ai_calls}",
        f"Rules matched: {_rule_summary(report)}",
        "",
        "RULE",
    ]
    if report.rule_findings:
        for finding in report.rule_findings:
            lines.append(
                f"- {finding.rule_id} [{finding.severity}] {finding.resource}: "
                f"{_single_line(finding.title)} - {_single_line(finding.message)}"
            )
    else:
        lines.append("None.")

    lines.extend(["", "AI VERIFIED"])
    if verified:
        for finding in verified:
            lines.append(
                f"- {finding.id} [{finding.severity}] {finding.resource}: "
                f"{_single_line(finding.claim)}"
            )
            lines.append(f"  Action: {_single_line(finding.recommended_action)}")
            for evidence in _evidence_lines(finding):
                lines.append(f"  Evidence: {evidence}" if ": " in evidence and not evidence.startswith(("Source:", "Retrieved:")) else f"  {evidence}")
            lines.append(f"  {_compile_hint(finding)}")
    else:
        lines.append("None.")

    lines.extend(["", "AI UNVERIFIED"])
    if unverified:
        for finding in unverified:
            lines.append(
                f"- {finding.id} [{finding.severity}] {finding.resource}: "
                f"{_single_line(finding.claim)}"
            )
            lines.append(
                f"  Reason: {_single_line(finding.verification_reason or 'evidence could not be verified')}"
            )
            for evidence in _evidence_lines(finding):
                lines.append(f"  {evidence}")
    else:
        lines.append("None.")

    lines.extend(["", "Conditions to merge"])
    lines.extend(f"- {_single_line(item)}" for item in report.conditions)
    if not report.conditions:
        lines.append("None.")

    lines.extend(["", "Steps"])
    lines.extend(
        f"Step {number}: {_single_line(step)}"
        for number, step in enumerate(report.trace_steps, 1)
    )
    if not report.trace_steps:
        lines.append("None.")

    lines.extend(["", "Ask you"])
    ask_items = _ask_items(report)
    lines.extend(f"- {_single_line(item)}" for item in ask_items)
    if not ask_items:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def render_markdown(report: Report) -> str:
    """Render a Markdown report for reports/latest.md."""
    verified, unverified = _ai_groups(report)
    lines = [
        "# ARGUS report",
        "",
        f"**Verdict:** {_markdown_text(report.verdict)}",
        f"**Run at:** {_markdown_text(report.run_at)}",
        f"**Elapsed:** {report.elapsed_seconds:.2f} seconds",
        f"**AI calls:** {report.ai_calls}",
        f"**Rules matched:** {_markdown_text(_rule_summary(report))}",
        "",
        "## RULE",
        "",
    ]
    if report.rule_findings:
        for finding in report.rule_findings:
            lines.append(
                f"- **{finding.rule_id} [{finding.severity}]** "
                f"{_markdown_text(finding.resource)}: {_markdown_text(finding.title)} — "
                f"{_markdown_text(finding.message)}"
            )
    else:
        lines.append("None.")

    lines.extend(["", "## AI VERIFIED", ""])
    if verified:
        for finding in verified:
            lines.append(
                f"- **{finding.id} [{finding.severity}]** "
                f"{_markdown_text(finding.resource)}: {_markdown_text(finding.claim)}"
            )
            lines.append(f"  - Action: {_markdown_text(finding.recommended_action)}")
            for evidence in _evidence_lines(finding):
                lines.append(f"  - Evidence: {_markdown_text(evidence)}" if not evidence.startswith(("Source:", "Retrieved:")) else f"  - {_markdown_text(evidence)}")
            lines.append(f"  - {_markdown_text(_compile_hint(finding))}")
    else:
        lines.append("None.")

    lines.extend(["", "## AI UNVERIFIED", ""])
    if unverified:
        for finding in unverified:
            lines.append(
                f"- **{finding.id} [{finding.severity}]** "
                f"{_markdown_text(finding.resource)}: {_markdown_text(finding.claim)}"
            )
            lines.append(
                f"  - Reason: {_markdown_text(finding.verification_reason or 'evidence could not be verified')}"
            )
            for evidence in _evidence_lines(finding):
                lines.append(f"  - {_markdown_text(evidence)}")
    else:
        lines.append("None.")

    lines.extend(["", "## Conditions to merge", ""])
    lines.extend(f"- {_markdown_text(item)}" for item in report.conditions)
    if not report.conditions:
        lines.append("None.")

    lines.extend(["", "## Steps", ""])
    lines.extend(
        f"- Step {number}: {_markdown_text(step)}"
        for number, step in enumerate(report.trace_steps, 1)
    )
    if not report.trace_steps:
        lines.append("None.")

    lines.extend(["", "## Ask you", ""])
    ask_items = _ask_items(report)
    lines.extend(f"- {_markdown_text(item)}" for item in ask_items)
    if not ask_items:
        lines.append("None.")
    return "\n".join(lines).rstrip() + "\n"


def _html_text(value: str) -> str:
    return escape(_single_line(value), quote=True)


def _html_evidence(finding: AIFinding) -> str:
    if not finding.evidence:
        return ""
    items: list[str] = []
    for item in finding.evidence:
        doc_id = _html_text(item.get("doc_id", "unknown document"))
        quote = _html_text(item.get("quote", ""))
        source = _html_text(item.get("url", ""))
        retrieved = _html_text(item.get("retrieved_at", ""))
        details = f"<strong>{doc_id}</strong>: <q>{quote}</q>"
        if source:
            details += f" <span>Source: {source}</span>"
        if retrieved:
            details += f" <span>Retrieved: {retrieved}</span>"
        items.append(f"<li>{details}</li>")
    return "<ul class=\"evidence\">" + "".join(items) + "</ul>"


def _html_group(items: list[str]) -> str:
    return "<ul>" + "".join(items) + "</ul>" if items else "<p>None.</p>"


def render_html(report: Report) -> str:
    """Render a self-contained HTML report with escaped data."""
    verified, unverified = _ai_groups(report)
    rules = [
        "<li><strong>"
        + _html_text(finding.rule_id)
        + "</strong> ["
        + _html_text(finding.severity)
        + "] "
        + _html_text(finding.resource)
        + ": "
        + _html_text(finding.title)
        + " — "
        + _html_text(finding.message)
        + "</li>"
        for finding in report.rule_findings
    ]
    verified_items = [
        "<li><strong>"
        + _html_text(finding.id)
        + "</strong> ["
        + _html_text(finding.severity)
        + "] "
        + _html_text(finding.resource)
        + ": "
        + _html_text(finding.claim)
        + "<p>Action: "
        + _html_text(finding.recommended_action)
        + "</p>"
        + _html_evidence(finding)
        + "<p>"
        + _html_text(_compile_hint(finding))
        + "</p></li>"
        for finding in verified
    ]
    unverified_items = [
        "<li><strong>"
        + _html_text(finding.id)
        + "</strong> ["
        + _html_text(finding.severity)
        + "] "
        + _html_text(finding.resource)
        + ": "
        + _html_text(finding.claim)
        + "<p>Reason: "
        + _html_text(finding.verification_reason or "evidence could not be verified")
        + "</p>"
        + _html_evidence(finding)
        + "</li>"
        for finding in unverified
    ]
    conditions = [f"<li>{_html_text(item)}</li>" for item in report.conditions]
    steps = [
        f"<li>Step {number}: {_html_text(step)}</li>"
        for number, step in enumerate(report.trace_steps, 1)
    ]
    ask_items = [f"<li>{_html_text(item)}</li>" for item in _ask_items(report)]
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>ARGUS report</title>\n"
        "<style>"
        "body{font:16px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#17212b}"
        "h1,h2{line-height:1.2}section{border-top:1px solid #d8e0e8;margin-top:1.5rem;padding-top:.5rem}"
        "li{margin:.5rem 0}ul.evidence{font-size:.9rem;color:#34485e}"
        "q{overflow-wrap:anywhere}span{display:block}strong{font-weight:700}"
        "</style>\n</head>\n<body>\n<main>\n"
        "<h1>ARGUS report</h1>\n"
        f"<p><strong>Verdict:</strong> {_html_text(report.verdict)}<br>"
        f"<strong>Run at:</strong> {_html_text(report.run_at)}<br>"
        f"<strong>Elapsed:</strong> {report.elapsed_seconds:.2f} seconds<br>"
        f"<strong>AI calls:</strong> {report.ai_calls}<br>"
        f"<strong>Rules matched:</strong> {_html_text(_rule_summary(report))}</p>\n"
        f"<section><h2>RULE</h2>{_html_group(rules)}</section>\n"
        f"<section><h2>AI VERIFIED</h2>{_html_group(verified_items)}</section>\n"
        f"<section><h2>AI UNVERIFIED</h2>{_html_group(unverified_items)}</section>\n"
        f"<section><h2>Conditions to merge</h2>{_html_group(conditions)}</section>\n"
        f"<section><h2>Steps</h2>{_html_group(steps)}</section>\n"
        f"<section><h2>Ask you</h2>{_html_group(ask_items)}</section>\n"
        "</main>\n</body>\n</html>\n"
    )


def write_reports(report: Report, output_dir: Path) -> tuple[Path, Path]:
    """Write the latest Markdown and HTML reports and return their paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "latest.md"
    html_path = output_dir / "latest.html"
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return markdown_path, html_path
