"""G22: check explicit resource regions against organization policy."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class ApprovedRegion(ContextRule):
    id = "G22"
    title = "Region not approved"
    severity = "high"
    why_it_matters = "A resource outside approved regions may breach placement requirements."
    how_to_fix = "Use a region listed in the organization's governance configuration."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        findings = []
        if not context.approved_regions:
            return findings
        for change in changes:
            after = change.after or {}
            region = after.get("region") or after.get("aws_region") or change.tags.get("region")
            if isinstance(region, str) and region and region not in context.approved_regions:
                findings.append(context_finding(
                    self, change.address, f"Region {region} is not in the approved regions list.",
                ))
        return findings
