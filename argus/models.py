"""Provider-neutral records consumed by ARGUS rules."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Change:
    """One planned infrastructure resource change from a source adapter."""

    address: str
    resource_type: str
    canonical_type: str
    actions: tuple[str, ...]
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    replace_paths: tuple[tuple[str | int, ...], ...]
    tags: dict[str, str]
    is_replace: bool
    source_tool: str = "terraform"
