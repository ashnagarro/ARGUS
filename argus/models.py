"""Provider-neutral records consumed by ARGUS rules."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Change:
    """One planned infrastructure resource change from a source adapter."""

    address: str
    resource_type: str
    canonical_type: str
    actions: tuple[str, ...]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    replace_paths: tuple[tuple[str | int, ...], ...]
    tags: dict[str, str]
    is_replace: bool
    source_tool: str = "terraform"

@dataclass(frozen=True, slots=True)
class RuleFinding:
    """A deterministic rule result with no AI-supplied evidence."""

    rule_id: str
    resource: str
    title: str
    severity: str
    message: str
    controls: tuple[str, ...] = ()
    source_doc_ids: tuple[str, ...] = ()
    headline: str = ""
    tags: dict[str, str] | None = None
    why_it_matters: str = ""
    how_to_fix: str = ""
    source_finding_id: str = ""
    human_approved_on: str = ""
    waived: bool = False
    waiver_reason: str | None = None
    waiver_expires: str | None = None

@dataclass(frozen=True, slots=True)
class AIFinding:
    """An AI claim and its code-verified status for reporting."""

    id: str
    resource: str
    claim: str
    severity: str
    recommended_action: str
    verified: bool
    verification_reason: str | None = None
    evidence: tuple[dict[str, str], ...] = ()
    change_type: str = ""
    confidence: str = ""
    headline: str = ""
    tags: dict[str, str] | None = None
