"""G21: require organization-defined resource tags."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class RequiredTags(ContextRule):
    id = "G21"
    name = "required-metadata-missing"
    title = "Required resource metadata missing"
    applies_to = ("terraform/aws",)
    severity = "high"
    why_it_matters = "Missing ownership or classification tags prevent consistent review."
    how_to_fix = "Add every tag required by the organization's governance configuration."

    @staticmethod
    def _supports_tags(change: Change) -> bool:
        # Terraform includes tag attributes in the state of taggable resources,
        # even when the current tag map is empty. Avoid blocking resources that
        # have no way to accept the configured tags.
        return bool(change.tags) or any(
            isinstance(state, dict) and ("tags" in state or "tags_all" in state)
            for state in (change.before, change.after)
        )

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        findings = []
        for change in changes:
            if ("delete" in change.actions and "create" not in change.actions
                    or not self._supports_tags(change)):
                continue
            missing = [tag for tag in context.required_tags if not change.tags.get(tag)]
            if missing:
                findings.append(context_finding(
                    self, change.address, f"Missing required tags: {', '.join(missing)}.",
                ))
        return findings
