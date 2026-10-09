"""Base class and auto-loading for deterministic rules."""

from abc import ABC, abstractmethod
from importlib import import_module
import inspect
from pkgutil import iter_modules
from typing import ClassVar, Collection, Sequence

from argus.models import Change, RuleFinding


class Rule(ABC):
    """One deterministic check over normalized Change records."""

    id: ClassVar[str]
    title: ClassVar[str]
    severity: ClassVar[str]
    controls: ClassVar[tuple[str, ...]] = ()
    source_doc_ids: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        """Return findings triggered by this change."""

    def finding(self, change: Change, message: str) -> RuleFinding:
        """Create a finding with this rule's metadata."""
        return RuleFinding(
            rule_id=self.id,
            resource=change.address,
            title=self.title,
            severity=self.severity,
            message=message,
            controls=self.controls,
            source_doc_ids=self.source_doc_ids,
        )


def load_rules() -> list[Rule]:
    """Import every module in this package and instantiate its Rule subclass."""
    rules: list[Rule] = []
    for module_info in iter_modules(__path__):
        module = import_module(f"{__name__}.{module_info.name}")
        for _, rule_class in inspect.getmembers(module, inspect.isclass):
            if (issubclass(rule_class, Rule) and rule_class is not Rule
                    and rule_class.__module__ == module.__name__):
                rules.append(rule_class())
    rules.sort(key=lambda rule: rule.id)
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate deterministic rule ID")
    return rules


def run_rules(
    changes: Sequence[Change], *, disabled_rule_ids: Collection[str] = (),
) -> list[RuleFinding]:
    """Apply all loaded rules to normalized changes."""
    all_changes = tuple(changes)
    return [finding
            for rule in load_rules() if rule.id not in disabled_rule_ids
            for change in all_changes
            for finding in rule.check(change, all_changes)]
