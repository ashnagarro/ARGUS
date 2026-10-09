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
from argus.warden import W001_ID, W001_NAME


class Rule(ABC):
    """One deterministic check over normalized Change records."""

    id: ClassVar[str]
    name: ClassVar[str] = ""
    title: ClassVar[str]
    applies_to: ClassVar[tuple[str, ...]] = ()
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
        if (self.id == "R001" and change.canonical_type == "data_store"
                and change.resource_type in ("aws_db_instance", "aws_rds_cluster")):
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
            name=self.name or self.id.lower(),
            applies_to=self.applies_to,
            source_tool=change.source_tool,
            cloud="aws" if change.resource_type.startswith("aws_") else "",
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
    names = [rule.name for rule in rules]
    if len(names) != len(set(names)) or W001_NAME in names:
        raise ValueError("Duplicate deterministic rule name")
    return rules


def resolve_rule_id(reference: str) -> str | None:
    """Resolve an audit ID or readable rule name to its stable audit ID."""
    normalized = reference.strip()
    if normalized.upper() == W001_ID or normalized.lower() == W001_NAME:
        return W001_ID
    for rule in load_rules(include_governance=True):
        if normalized.upper() == rule.id or normalized.lower() == rule.name:
            return rule.id
    return None


def run_rules(
    changes: Sequence[Change], *, disabled_rule_ids: Collection[str] = (),
    include_governance: bool = False,
    governance_context: GovernanceContext | None = None,
    controls_path: Path | None = None,
    enabled_rule_ids: Collection[str] | None = None,
    extra_rules: Sequence[Rule] = (),
) -> list[RuleFinding]:
    """Apply all loaded rules to normalized changes."""
    all_changes = tuple(changes)
    context = governance_context or GovernanceContext()
    findings: list[RuleFinding] = []
    rules = load_rules(include_governance=include_governance, controls_path=controls_path)
    rules.extend(extra_rules)
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate deterministic rule ID")
    for rule in rules:
        if rule.id in disabled_rule_ids or rule.name in disabled_rule_ids:
            continue
        if enabled_rule_ids is not None and rule.id not in enabled_rule_ids:
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
