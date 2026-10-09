"""Base class and auto-loading for deterministic rules."""

from abc import ABC, abstractmethod
from importlib import import_module
import inspect
from pkgutil import iter_modules
import re
from pathlib import Path
from typing import ClassVar, Collection, Sequence

from argus.governance import GovernanceContext, load_controls
from argus.models import Change, RuleFinding


class Rule(ABC):
    """One deterministic check over normalized Change records."""

    id: ClassVar[str]
    title: ClassVar[str]
    severity: ClassVar[str]
    controls: ClassVar[tuple[str, ...]] = ()
    source_doc_ids: ClassVar[tuple[str, ...]] = ()
    why_it_matters: ClassVar[str]
    how_to_fix: ClassVar[str]
    source_finding_id: ClassVar[str] = ""
    human_approved_on: ClassVar[str] = ""

    @abstractmethod
    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        """Return findings triggered by this change."""

    def finding(self, change: Change, message: str) -> RuleFinding:
        """Create a finding with this rule's metadata."""
        tags = {key: change.tags[key] for key in ("env", "data_classification", "owner")
                if key in change.tags}
        headline = self.title
        if self.id == "R001" and change.canonical_type in ("database_instance", "database_cluster"):
            environment = "Production" if tags.get("env", "").lower() in ("prod", "production") else "A"
            classification = " holding PII" if "pii" in tags.get("data_classification", "").lower() else ""
            headline = f"{environment} database{classification} will be deleted and recreated"
        return RuleFinding(
            rule_id=self.id,
            resource=change.address,
            title=self.title,
            severity=self.severity,
            message=message,
            controls=self.controls,
            source_doc_ids=self.source_doc_ids,
            headline=headline, tags=tags,
            why_it_matters=self.why_it_matters, how_to_fix=self.how_to_fix,
            source_finding_id=self.source_finding_id,
            human_approved_on=self.human_approved_on,
        )


def load_rules(
    *, include_governance: bool = False, controls_path: Path | None = None,
) -> list[Rule]:
    """Load baseline rules and, when enabled, the governance pack."""
    rules: list[Rule] = []
    controls = load_controls(controls_path) if include_governance and controls_path else {}
    for module_info in iter_modules(__path__):
        if not re.fullmatch(r"(?:r\d{3}|g\d\d)", module_info.name):
            continue
        if re.fullmatch(r"g\d\d", module_info.name) and not include_governance:
            continue
        module = import_module(f"{__name__}.{module_info.name}")
        for _, rule_class in inspect.getmembers(module, inspect.isclass):
            if (issubclass(rule_class, Rule) and rule_class is not Rule
                    and rule_class.__module__ == module.__name__):
                rule = rule_class()
                if rule.id.startswith("G"):
                    rule.controls = controls.get(rule.id, ())
                rules.append(rule)
    rules.sort(key=lambda rule: rule.id)
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate deterministic rule ID")
    return rules


def run_rules(
    changes: Sequence[Change], *, disabled_rule_ids: Collection[str] = (),
    include_governance: bool = False,
    governance_context: GovernanceContext | None = None,
    controls_path: Path | None = None,
) -> list[RuleFinding]:
    """Apply all loaded rules to normalized changes."""
    all_changes = tuple(changes)
    context = governance_context or GovernanceContext()
    findings: list[RuleFinding] = []
    for rule in load_rules(include_governance=include_governance, controls_path=controls_path):
        if rule.id in disabled_rule_ids:
            continue
        if rule.id == "G17":
            rule.minimum_retention_days = context.minimum_retention_days
        for change in all_changes:
            findings.extend(rule.check(change, all_changes))
        if include_governance:
            check_context = getattr(rule, "check_context", None)
            if callable(check_context):
                findings.extend(check_context(all_changes, context))
    return findings
