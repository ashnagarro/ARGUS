"""Deterministic verdicts and merge conditions."""

from collections.abc import Sequence
from typing import Literal

from .models import AIFinding, RuleFinding


Verdict = Literal["GO", "GO-WITH-CONDITIONS", "NO-GO"]
_BLOCKING_SEVERITIES = frozenset({"high", "critical"})
VERDICT_LABELS = {
    "GO": "GO",
    "GO-WITH-CONDITIONS": "GO WITH CONDITIONS",
    "NO-GO": "NO-GO",
    "NEEDS HUMAN": "HOLD FOR REVIEW",
    "NEEDS_HUMAN": "HOLD FOR REVIEW",
}
HOLD_EXPLANATION = (
    "ARGUS could not complete its checks, so this change is blocked until a person reviews it."
)


def verdict_label(value: str) -> str:
    """Convert a stored verdict into its human-facing label."""
    return VERDICT_LABELS.get(value, value)


def verdict_explanation(value: str) -> str:
    """Explain the blocked, incomplete-review state only."""
    return HOLD_EXPLANATION if verdict_label(value) == "HOLD FOR REVIEW" else ""


def decide_verdict(
    rule_findings: Sequence[RuleFinding],
    ai_findings: Sequence[AIFinding] = (),
) -> Verdict:
    """Rule findings block; verified AI findings add conditions."""
    if any(not finding.waived and finding.severity.lower() in _BLOCKING_SEVERITIES
           for finding in rule_findings):
        return "NO-GO"
    if any(finding.verified for finding in ai_findings):
        return "GO-WITH-CONDITIONS"
    return "GO"


def merge_conditions(
    rule_findings: Sequence[RuleFinding],
    ai_findings: Sequence[AIFinding] = (),
) -> tuple[str, ...]:
    """Describe the actions needed before a change can merge."""
    conditions = [
        finding.how_to_fix or finding.message
        for finding in rule_findings
        if not finding.waived and finding.severity.lower() in _BLOCKING_SEVERITIES
    ]
    conditions.extend(
        finding.recommended_action
        for finding in ai_findings
        if finding.verified and finding.recommended_action
    )
    return tuple(conditions)
