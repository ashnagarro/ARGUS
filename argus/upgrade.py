"""Extract provider upgrade risks from Terraform configuration and a local guide."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .corpus import Document, Section
from .models import AIFinding, Change


GUIDE_ID = "terraform-aws-provider-v5-upgrade"
GUIDE_QUOTE = "Change `name` to `db_name` in configurations as `name` no longer exists."
_VERSION = re.compile(r"\d+(?:\.\d+){1,2}\Z")
_LOCK_PROVIDER = re.compile(
    r'provider\s+"(?:registry\.terraform\.io/)?hashicorp/([a-z0-9_-]+)"\s*\{([^}]*)\}',
    re.DOTALL,
)
_LOCK_VERSION = re.compile(r'\bversion\s*=\s*"([^"]+)"')
_CHANGED_ARG = re.compile(r"(?i)\b(?:change|remove|rename|removed)\s+`([a-z][a-z0-9_.]*)`")
_GONE_ARG = re.compile(r"(?i)`([a-z][a-z0-9_.]*)`\s+(?:which\s+)?no longer exists\b")


@dataclass(frozen=True, slots=True)
class UpgradeSpec:
    provider: str
    from_version: str
    to_version: str

    def __post_init__(self) -> None:
        if self.provider != "aws":
            raise ValueError("only the AWS provider upgrade guide is available")
        if not _VERSION.fullmatch(self.from_version) or not _VERSION.fullmatch(self.to_version):
            raise ValueError("provider versions must be numeric major.minor[.patch] values")
        if self.from_version.split(".")[0] != "4" or self.to_version.split(".")[0] != "5":
            raise ValueError("the local upgrade guide covers AWS provider 4.x to 5.x only")


def lock_version(path: Path, provider: str) -> str:
    """Read the pinned HashiCorp provider version from a Terraform lock file."""
    content = Path(path).read_text(encoding="utf-8")
    for found_provider, body in _LOCK_PROVIDER.findall(content):
        if found_provider == provider:
            version = _LOCK_VERSION.search(body)
            if version:
                return version.group(1)
    raise ValueError(f"{path}: no pinned hashicorp/{provider} provider version")


def resolve_upgrade(
    provider: str, from_version: str | None, to_version: str | None,
    lock_before: Path | None = None, lock_after: Path | None = None,
) -> UpgradeSpec:
    """Accept either an explicit version pair or two provider lock files."""
    versions = from_version is not None or to_version is not None
    locks = lock_before is not None or lock_after is not None
    if versions == locks:
        raise ValueError("provide --from and --to, or --lock-before and --lock-after")
    if versions:
        if not from_version or not to_version:
            raise ValueError("both --from and --to are required")
        return UpgradeSpec(provider, from_version, to_version)
    if lock_before is None or lock_after is None:
        raise ValueError("both --lock-before and --lock-after are required")
    return UpgradeSpec(provider, lock_version(lock_before, provider),
                       lock_version(lock_after, provider))


def _resource_sections(document: Document, resource_type: str) -> tuple[Section, ...]:
    heading = f"resource/{resource_type}"
    selected: list[Section] = []
    in_resource = False
    for section in document.sections:
        if section.heading == heading:
            in_resource = True
        elif section.heading.startswith(("resource/", "data-source/")):
            in_resource = False
        if in_resource:
            selected.append(section)
    return tuple(selected)


def _breaking_arguments(text: str) -> set[str]:
    """Read only explicitly changed or removed old argument names from guide prose."""
    arguments: set[str] = set()
    for line in text.splitlines():
        if not re.search(r"(?i)\b(?:change|remove|removed|rename|no longer exists)\b", line):
            continue
        for pattern in (_CHANGED_ARG, _GONE_ARG):
            arguments.update(match.group(1).split(".", 1)[0] for match in pattern.finditer(line))
    return arguments


def _configured_resources(module: Mapping[str, Any]) -> list[dict[str, Any]]:
    resources = module.get("resources", [])
    if not isinstance(resources, list):
        raise ValueError("configuration module resources must be a list")
    found = [item for item in resources if isinstance(item, dict) and item.get("mode", "managed") == "managed"]
    calls = module.get("module_calls", {})
    if not isinstance(calls, dict):
        raise ValueError("configuration module_calls must be an object")
    for call in calls.values():
        if isinstance(call, dict) and isinstance(call.get("module"), dict):
            found.extend(_configured_resources(call["module"]))
    return found


def collect_upgrade_changes(plan: Path, spec: UpgradeSpec, document: Document) -> tuple[Change, ...]:
    """Create one change for each configured resource type using a changed argument."""
    source = json.loads(Path(plan).read_text(encoding="utf-8"))
    if not isinstance(source, dict) or not isinstance(source.get("configuration"), dict):
        raise ValueError("Terraform plan JSON needs a configuration section")
    root = source["configuration"].get("root_module")
    if not isinstance(root, dict):
        raise ValueError("Terraform configuration needs a root_module")
    by_type: dict[str, set[str]] = {}
    for resource in _configured_resources(root):
        resource_type = resource.get("type")
        expressions = resource.get("expressions", {})
        if not isinstance(resource_type, str) or not isinstance(expressions, dict):
            raise ValueError("configured resources need a type and expressions object")
        if resource_type.startswith(f"{spec.provider}_"):
            by_type.setdefault(resource_type, set()).update(str(name) for name in expressions)
    changes: list[Change] = []
    for resource_type, arguments in sorted(by_type.items()):
        sections = _resource_sections(document, resource_type)
        changed = set().union(*(_breaking_arguments(section.text) for section in sections)) if sections else set()
        if not arguments.intersection(changed):
            continue
        changes.append(Change(
            address=f"provider-upgrade:{resource_type}", resource_type=resource_type,
            canonical_type="provider-upgrade", source_tool="terraform",
            actions=("upgrade",), before=None, after=None, replace_paths=(), tags={},
            is_replace=False, provider=spec.provider, from_version=spec.from_version,
            to_version=spec.to_version, arguments_used=tuple(sorted(arguments)),
        ))
    return tuple(changes)


def filter_upgrade_findings(
    findings: Sequence[AIFinding], changes: Sequence[Change], document: Document,
) -> tuple[AIFinding, ...]:
    """Keep verified status only for cited changes to arguments used by this plan."""
    by_address = {change.address: change for change in changes}
    checked: list[AIFinding] = []
    for finding in findings:
        if not finding.verified:
            checked.append(finding)
            continue
        change = by_address.get(finding.resource)
        if change is None:
            checked.append(replace(finding, verified=False, verification_reason="resource_mismatch"))
            continue
        sections = _resource_sections(document, change.resource_type)
        allowed = False
        for evidence in finding.evidence:
            quote = evidence.get("quote", "")
            if (evidence.get("doc_id") == document.doc_id
                    and any(" ".join(quote.split()) in " ".join(section.text.split()) for section in sections)
                    and _breaking_arguments(quote).intersection(change.arguments_used)):
                allowed = True
                break
        checked.append(finding if allowed else replace(
            finding, verified=False, verification_reason="argument_not_changed_in_guide"))
    return tuple(checked)


def seed_demo_replay(
    changes: Sequence[Change], document: Document, *, model: str,
    schema_path: Path, cache_dir: Path,
) -> None:
    """Prepare a synthetic, quoted Scholar replay for the offline Act 8 demonstration."""
    from .scholar import _cache_key, _write_cache

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    documents = {document.doc_id: document}
    for change in changes:
        if change.resource_type != "aws_db_instance" or "name" not in change.arguments_used:
            continue
        section = next((item for item in _resource_sections(document, change.resource_type)
                        if GUIDE_QUOTE in item.text), None)
        if section is None:
            raise ValueError("Act 8 demo quote is absent from the fetched upgrade guide")
        cache_path = cache_dir / f"{_cache_key(change, documents, model, schema)}.json"
        if cache_path.is_file():
            continue
        calls = (
            ("get_change", {}),
            ("search_corpus", {"query": "aws_db_instance name db_name provider v5"}),
            ("read_section", {"doc_id": document.doc_id, "number": section.number}),
            ("verify_quote", {"doc_id": document.doc_id, "quote": GUIDE_QUOTE}),
        )
        records = [
            {"output": [{"type": "function_call", "name": name,
                         "arguments": json.dumps(arguments), "call_id": f"act8-{index}"}],
             "output_text": ""}
            for index, (name, arguments) in enumerate(calls, 1)
        ]
        records.append({"output": [], "output_text": json.dumps({"findings": [{
            "id": "F8", "resource": change.address,
            "change_type": "provider_upgrade_breaking_argument",
            "claim": "The configured name argument was removed in AWS provider v5.",
            "evidence": [{"doc_id": document.doc_id, "quote": GUIDE_QUOTE}],
            "severity": "high", "recommended_action": "Replace name with db_name.",
            "confidence": "high",
        }]})})
        _write_cache(cache_path, tuple(records))
