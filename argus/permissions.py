"""Small, fail-closed permission policy for ARGUS tools and changes."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    read_only_tools: frozenset[str]
    sensitive_resource_patterns: tuple[str, ...]
    write_actions_require_approval: bool


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    decision: str
    reason: str

    @property
    def approved(self) -> bool:
        return self.decision == "auto"


def load_policy(path: Path = Path("permissions.yaml")) -> PermissionPolicy:
    """Read the intentionally small YAML subset used by permissions.yaml.

    Unknown keys and malformed entries fail closed. No YAML dependency is needed.
    """
    lists = {"read_only_tools": [], "sensitive_resource_patterns": []}
    scalar: bool | None = None
    current: str | None = None
    seen: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(" #", 1)[0].rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, colon, value = line.partition(":")
            if not colon or key not in {*lists, "write_actions_require_approval"} or key in seen:
                raise ValueError(f"{path}:{number}: invalid permission key")
            seen.add(key)
            if key in lists:
                if value.strip():
                    raise ValueError(f"{path}:{number}: expected a list")
                current = key
            else:
                if value.strip() not in {"true", "false"}:
                    raise ValueError(f"{path}:{number}: expected true or false")
                scalar = value.strip() == "true"
                current = None
        elif current is not None and line.startswith("  - "):
            item = line[4:].strip()
            if not item or any(char.isspace() for char in item):
                raise ValueError(f"{path}:{number}: invalid list item")
            lists[current].append(item)
        else:
            raise ValueError(f"{path}:{number}: invalid permission entry")
    if seen != {*lists, "write_actions_require_approval"} or scalar is None:
        raise ValueError(f"{path}: incomplete permission policy")
    if not scalar:
        raise ValueError(f"{path}: write actions must require human approval")
    return PermissionPolicy(
        frozenset(lists["read_only_tools"]),
        tuple(lists["sensitive_resource_patterns"]),
        scalar,
    )


def decide_permission(
    action_name: str,
    resource_type: str,
    *,
    is_write: bool,
    policy: PermissionPolicy,
) -> PermissionDecision:
    """Decide before running a tool; unknown actions require a human."""
    if is_write:
        return PermissionDecision("requires_human_approval", "write action")
    if any(fnmatchcase(resource_type, pattern) for pattern in policy.sensitive_resource_patterns):
        return PermissionDecision("requires_human_approval", "sensitive resource type")
    if action_name not in policy.read_only_tools:
        return PermissionDecision("requires_human_approval", "action is not allowlisted")
    return PermissionDecision("auto", "read-only tool")
