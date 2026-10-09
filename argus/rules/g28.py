"""G28: sensitive agent infrastructure changes require a human approver."""

from __future__ import annotations

from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


class SensitiveAgentApproval(ContextRule):
    id = "G28"
    title = "Sensitive agent change needs human approval"
    severity = "critical"
    why_it_matters = "IAM, security-group, and KMS changes can alter access to infrastructure."
    how_to_fix = "Obtain review from a distinct human and provide --approver."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        if not context.author.startswith("agent:"):
            return []
        approved = bool(context.approver and not context.approver.startswith("agent:")
                        and context.approver.strip().lower() != context.author[6:].strip().lower())
        if approved:
            return []
        return [context_finding(self, change.address,
                                "Agent change to IAM, security group, or KMS lacks a human approver.")
                for change in changes
                if change.resource_type.startswith((
                    "aws_iam_", "aws_security_group", "aws_vpc_security_group", "aws_kms_",
                ))]
