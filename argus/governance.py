"""Configuration and run context for the optional governance rule pack."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from .models import RuleFinding


@dataclass(frozen=True, slots=True)
class GovernanceContext:
    required_tags: tuple[str, ...] = ()
    approved_regions: tuple[str, ...] = ()
    allowed_instance_classes: tuple[str, ...] = ()
    minimum_retention_days: int | None = None
    ticket: str | None = None
    author: str = "human"
    approver: str | None = None
    tf_files: tuple[Path, ...] = ()
    ledger_recorded: bool = True


def _strings(settings: Mapping[str, Any], key: str) -> tuple[str, ...]:
    raw = settings.get(key, [])
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"[governance] {key} must be a list of nonempty strings")
    return tuple(raw)


def context_from_settings(
    settings: Mapping[str, Any], *, ticket: str | None = None,
    author: str = "human", approver: str | None = None,
    tf_files: tuple[Path, ...] = (), ledger_recorded: bool = True,
) -> GovernanceContext:
    """Treat absent organization thresholds as unset, never as invented policy."""
    section = settings.get("governance", {})
    if not isinstance(section, dict):
        raise ValueError("[governance] must be a table")
    minimum = section.get("minimum_retention_days")
    if minimum is not None and (type(minimum) is not int or minimum < 1):
        raise ValueError("[governance] minimum_retention_days must be a positive integer")
    return GovernanceContext(
        required_tags=_strings(section, "required_tags"),
        approved_regions=_strings(section, "approved_regions"),
        allowed_instance_classes=_strings(section, "allowed_instance_classes"),
        minimum_retention_days=minimum,
        ticket=ticket, author=author, approver=approver,
        tf_files=tf_files, ledger_recorded=ledger_recorded,
    )


def load_controls(path: Path) -> dict[str, tuple[str, ...]]:
    """Read a JSON-formatted YAML mapping without adding a YAML dependency."""
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("controls.yaml must contain an object")
    mapping: dict[str, tuple[str, ...]] = {}
    for rule_id, control_ids in payload.items():
        if (not isinstance(rule_id, str) or not isinstance(control_ids, list)
                or any(not isinstance(item, str) or not item for item in control_ids)):
            raise ValueError("controls.yaml must map rule IDs to control ID lists")
        mapping[rule_id] = tuple(control_ids)
    return mapping


def context_finding(rule: Any, resource: str, message: str, *, severity: str | None = None) -> RuleFinding:
    """Create a finding for run or file checks that have no Terraform Change."""
    return RuleFinding(
        rule_id=rule.id, resource=resource, title=rule.title,
        severity=severity or rule.severity, message=message,
        controls=rule.controls, headline=rule.title,
        why_it_matters=rule.why_it_matters, how_to_fix=rule.how_to_fix,
    )
