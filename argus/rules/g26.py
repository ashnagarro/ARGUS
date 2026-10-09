"""G26: detect literal credentials in Terraform source files."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Sequence

from argus.governance import GovernanceContext, context_finding
from argus.models import Change, RuleFinding

from ._governance import ContextRule


_HARDCODED = re.compile(
    r'(?im)^\s*(?:password|secret|secret_key|secret_string|api_key|access_key|private_key)\s*=\s*"[^"\r\n]+"'
)


class HardcodedTerraformSecret(ContextRule):
    id = "G26"
    title = "Hardcoded secret in Terraform"
    severity = "critical"
    why_it_matters = "A literal credential in Terraform source can be exposed through code review or state."
    how_to_fix = "Remove the literal credential and use a managed secret reference."

    def check_context(self, changes: Sequence[Change], context: GovernanceContext) -> list[RuleFinding]:
        findings = []
        for file in dict.fromkeys(context.tf_files):
            path = Path(file)
            if path.suffix.lower() != ".tf":
                continue
            content = path.read_text(encoding="utf-8")
            if _HARDCODED.search(content):
                findings.append(context_finding(
                    self, str(path), "Terraform source contains a literal secret assignment.",
                ))
        return findings
