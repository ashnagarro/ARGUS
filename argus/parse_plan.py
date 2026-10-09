"""Select the adapter for an infrastructure plan source."""

from pathlib import Path
from typing import Any, Mapping

from .adapters import terraform
from .models import Change


PlanSource = str | Path | Mapping[str, Any]


def parse_plan(source: PlanSource, source_tool: str = "terraform") -> list[Change]:
    """Return provider-neutral changes from the selected plan adapter."""
    if source_tool == "terraform":
        return terraform.parse_plan(source)
    raise ValueError(f"Unsupported plan source tool: {source_tool}")
