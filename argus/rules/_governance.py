"""Shared helpers for governance checks needing run context."""

from __future__ import annotations

from typing import Any, Sequence

from argus.models import Change, RuleFinding

from . import Rule


class ContextRule(Rule):
    """A governance rule whose input is the whole run, not one resource."""

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        return []


def tag_values(change: Change, key: str) -> tuple[str, ...]:
    """Read both sides of a change so removing a risk tag cannot hide a downgrade."""
    values: list[str] = []
    for state in (change.before, change.after):
        if not isinstance(state, dict):
            continue
        for field in ("tags_all", "tags"):
            tags: Any = state.get(field)
            value = tags.get(key) if isinstance(tags, dict) else None
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    value = change.tags.get(key)
    if isinstance(value, str) and value.strip():
        values.append(value.strip())
    return tuple(dict.fromkeys(values))


def is_production(change: Change) -> bool:
    return any(value.lower() in {"prod", "production"}
               for value in tag_values(change, "env"))
