"""Shared helpers for governance checks needing run context."""

from __future__ import annotations

from typing import Sequence

from argus.models import Change, RuleFinding

from . import Rule


class ContextRule(Rule):
    """A governance rule whose input is the whole run, not one resource."""

    def check(self, change: Change, all_changes: Sequence[Change]) -> list[RuleFinding]:
        return []


def is_production(change: Change) -> bool:
    return change.tags.get("env", "").strip().lower() in {"prod", "production"}
