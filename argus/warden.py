"""Agent file scope and dated deterministic finding exceptions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Sequence

from .models import RuleFinding


def load_agents(path: Path) -> dict[str, tuple[str, ...]]:
    """Read the small agents.yaml allowlist without a YAML dependency."""
    agents: dict[str, list[str]] = {}
    current: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "agents:":
            continue
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current = line.strip()[:-1]
            if not current or current in agents:
                raise ValueError(f"{path}:{number}: duplicate or empty agent")
            agents[current] = []
        elif line.startswith("    - ") and current:
            pattern = line[6:].strip()
            if not pattern or pattern.startswith(("/", "\\")) or ".." in PurePosixPath(pattern).parts:
                raise ValueError(f"{path}:{number}: invalid allowed path")
            agents[current].append(pattern)
        else:
            raise ValueError(f"{path}:{number}: invalid agent entry")
    if not agents or any(not patterns for patterns in agents.values()):
        raise ValueError(f"{path}: agents need nonempty allowed paths")
    return {name: tuple(patterns) for name, patterns in agents.items()}


def _relative_file(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (not normalized or normalized.startswith("/") or ":" in normalized
            or any(part in ("", ".", "..") for part in path.parts)):
        raise ValueError(f"invalid changed file path: {value}")
    return path.as_posix()


def check_agent_files(
    author: str, changed_files: Sequence[str], agents: dict[str, tuple[str, ...]],
) -> tuple[RuleFinding, ...]:
    """Flag each proposed agent file change outside its named allowlist."""
    if not author.startswith("agent:"):
        return ()
    name = author.removeprefix("agent:")
    allowed = agents.get(name, ())
    findings: list[RuleFinding] = []
    for value in changed_files:
        file = _relative_file(value)
        if not any(fnmatchcase(file, pattern) for pattern in allowed):
            findings.append(RuleFinding(
                rule_id="W001", resource=file,
                title="Agent file outside allowed scope", severity="critical",
                message=f"Agent {name} is not allowed to change {file}.",
            ))
    return tuple(findings)


def load_exceptions(path: Path) -> tuple[dict[str, str], ...]:
    """Parse a list of flat exception records with required audit fields."""
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    required = {"rule_id", "resource", "owner", "reason", "ticket", "expires"}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line == "exceptions:":
            continue
        if line.startswith("  - "):
            if current is not None:
                records.append(current)
            current = {}
            line = "    " + line[4:]
        if not line.startswith("    ") or current is None:
            raise ValueError(f"{path}:{number}: invalid exception entry")
        key, separator, value = line.strip().partition(":")
        if not separator or key not in required or key in current or not value.strip():
            raise ValueError(f"{path}:{number}: invalid exception field")
        current[key] = value.strip().strip('"\'')
    if current is not None:
        records.append(current)
    for record in records:
        if set(record) != required:
            raise ValueError(f"{path}: exception requires {', '.join(sorted(required))}")
        date.fromisoformat(record["expires"])
    return tuple(records)


def apply_exceptions(
    findings: Sequence[RuleFinding], exceptions: Sequence[dict[str, str]],
    today: date,
) -> tuple[RuleFinding, ...]:
    """Mark active waivers and make expired matches visibly blocking."""
    result: list[RuleFinding] = []
    for finding in findings:
        matched = next((item for item in exceptions
                        if item["rule_id"] == finding.rule_id
                        and item["resource"] == finding.resource), None)
        if matched is None:
            result.append(finding)
        elif today <= date.fromisoformat(matched["expires"]):
            result.append(replace(
                finding, waived=True, waiver_reason=matched["reason"],
                waiver_expires=matched["expires"],
            ))
        else:
            result.append(replace(
                finding,
                message=f"{finding.message} Exception expired on {matched['expires']}.",
            ))
    return tuple(result)
