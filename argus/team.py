"""Team overlays and rule-pack metadata for the optional portability feature.

The CLI enables this module only when ``[flags].team_overlays`` is true.  The
baseline pack remains active even when a team supplies no overlay.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import inspect
from pathlib import Path
import re
import shutil
import tomllib
from typing import Any, Collection, Mapping, Sequence

from .models import RuleFinding


_PACK_NAMES = ("baseline", "aws-core", "governance")
_RULE_ID = re.compile(r"^[A-Z][A-Z0-9]{2,15}$")
_SEVERITY = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_BUILTIN_RULES = {
    "baseline": (*tuple(f"R{number:03d}" for number in range(1, 8)), "W001"),
    "aws-core": (),
    "governance": tuple(f"G{number:02d}" for number in (*range(1, 27), 28, 29)),
}
_INIT_TEXT = """# ARGUS team overlay. Run `argus check PLAN.json` from this directory.
# The organization baseline is always enabled. Team settings may only tighten it.
approved_regions = []          # Example: ["synthetic-east"]
required_tags = []             # Example: ["env", "owner", "cost_center"]
owners = []                    # Approved values for the resource owner tag.
enabled_packs = ["aws-core"]    # Add "governance" for G-series checks.
# extra_rules_dir = ".argus/rules"

# Severity may be raised, but never lowered.
# [severity_overrides]
# R001 = "critical"
"""


@dataclass(frozen=True, slots=True)
class PackManifest:
    name: str
    version: str
    owner: str
    description: str
    rule_ids: tuple[str, ...]
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class TeamPolicy:
    """Validated team settings with critical findings for unsafe relaxations."""

    root: Path
    approved_regions: tuple[str, ...]
    required_tags: tuple[str, ...]
    owners: tuple[str, ...]
    enabled_packs: tuple[str, ...]
    extra_rules_dir: Path | None
    severity_overrides: Mapping[str, str]
    disabled_rules: tuple[str, ...]
    mandatory_rule_ids: tuple[str, ...]
    active_rule_ids: tuple[str, ...]
    findings: tuple[RuleFinding, ...]


def _strings(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a list of nonempty strings")
    return tuple(dict.fromkeys(item.strip() for item in value))


def config_finding(message: str) -> RuleFinding:
    return RuleFinding(
        rule_id="CFG001", resource=".argus/team.toml",
        title="Unsafe team configuration", severity="critical", message=message,
        headline="Team configuration tries to relax organization policy",
        why_it_matters="A team overlay cannot bypass the organization baseline.",
        how_to_fix="Remove the relaxation or request a dated exception with an owner and ticket.",
    )


def _safe_relative_dir(root: Path, raw: str) -> Path:
    path = Path(raw)
    if (not raw or not path.parts or path.is_absolute() or path.drive
            or any(part in ("..", "") for part in path.parts)):
        raise ValueError("extra_rules_dir must be a project-relative directory")
    root_resolved = root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root_resolved):
        raise ValueError("extra_rules_dir must stay inside the project")
    if (root / path).is_symlink():
        raise ValueError("extra_rules_dir may not be a symlink")
    if target.exists() and not target.is_dir():
        raise ValueError("extra_rules_dir must be a directory")
    return target


def _read_manifest(path: Path, expected: str) -> PackManifest:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    required = ("name", "version", "owner", "description", "rule_ids")
    if any(key not in data for key in required) or data["name"] != expected:
        raise ValueError(f"{path}: invalid pack manifest")
    if any(not isinstance(data[key], str) or not data[key].strip()
           for key in required[:-1]):
        raise ValueError(f"{path}: name, version, owner, and description must be nonempty strings")
    ids = _strings(data["rule_ids"], f"{path}: rule_ids")
    if any(not _RULE_ID.fullmatch(rule_id) for rule_id in ids):
        raise ValueError(f"{path}: invalid rule ID")
    return PackManifest(expected, data["version"], data["owner"],
                        data["description"], ids, path)


def load_packs(root: Path, *, package_root: Path | None = None) -> dict[str, PackManifest]:
    """Load project manifests, then source-tree manifests, then built-in IDs.

    Built-in IDs keep a Git-installed CLI functional when no pack directory has
    been copied into the team's working directory.
    """
    source_root = package_root or Path(__file__).resolve().parents[1]
    manifests: dict[str, PackManifest] = {}
    for name in _PACK_NAMES:
        bundled = Path(__file__).resolve().parent / "assets" / "packs" / name / "pack.toml"
        project = root / "packs" / name / "pack.toml"
        source = source_root / "packs" / name / "pack.toml"
        # Team workspaces may add aws-core rules, but must not shadow the
        # built-in baseline or governance pack shipped with ARGUS.
        candidates = ((bundled, source) if name in ("baseline", "governance")
                      else (project, source, bundled))
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            manifests[name] = PackManifest(name, "1.0.0", "ARGUS",
                                           f"ARGUS {name} rules", _BUILTIN_RULES[name])
        else:
            manifests[name] = _read_manifest(path, name)
    return manifests


def load_team_policy(
    root: Path, org_settings: Mapping[str, Any], *,
    package_root: Path | None = None,
) -> TeamPolicy:
    """Merge org policy and team overlay without allowing baseline relaxation.

    ``org_settings`` is the parsed ``argus.toml``.  Callers append ``findings``
    to ordinary rule findings before exceptions and verdict calculation.
    """
    root = root.resolve()
    path = root / ".argus" / "team.toml"
    overlay = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if not isinstance(overlay, dict):
        raise ValueError(".argus/team.toml must contain a TOML table")
    allowed = {"approved_regions", "required_tags", "owners", "enabled_packs",
               "extra_rules_dir", "severity_overrides", "disabled_rules"}
    unknown = set(overlay) - allowed
    if unknown:
        raise ValueError(f".argus/team.toml has unknown settings: {', '.join(sorted(unknown))}")
    manifests = load_packs(root, package_root=package_root)
    governance = org_settings.get("governance", {})
    if not isinstance(governance, dict):
        raise ValueError("[governance] must be a table")
    org_tags = _strings(governance.get("required_tags", []), "[governance] required_tags")
    org_regions = _strings(governance.get("approved_regions", []), "[governance] approved_regions")
    org_classes = _strings(governance.get("allowed_instance_classes", []),
                           "[governance] allowed_instance_classes")
    org_retention = governance.get("minimum_retention_days")
    team_tags = _strings(overlay.get("required_tags", []), "required_tags")
    team_regions = _strings(overlay.get("approved_regions", []), "approved_regions")
    owners = _strings(overlay.get("owners", []), "owners")
    team_enabled = _strings(overlay.get("enabled_packs", ["aws-core"]), "enabled_packs")
    flags = org_settings.get("flags", {})
    if not isinstance(flags, dict):
        raise ValueError("[flags] must be a table")
    governance_required = bool(org_tags or org_regions or org_classes
                               or org_retention is not None or team_tags or team_regions)
    org_enabled = ("governance",) if flags.get("governance_pack") is True or governance_required else ()
    enabled = tuple(dict.fromkeys((*org_enabled, *team_enabled)))
    disabled = _strings(overlay.get("disabled_rules", []), "disabled_rules")
    findings: list[RuleFinding] = []
    if any(name not in manifests or name == "baseline" for name in enabled):
        findings.append(config_finding("Unknown or reserved pack in enabled_packs."))
    enabled = tuple(name for name in enabled if name in manifests and name != "baseline")
    baseline_ids = set(manifests["baseline"].rule_ids)
    mandatory_ids = set(baseline_ids)
    for name in org_enabled:
        mandatory_ids.update(manifests[name].rule_ids)
    for rule_id in disabled:
        if rule_id in mandatory_ids:
            findings.append(config_finding(f"Organization-mandated rule {rule_id} cannot be disabled."))
    if org_regions and team_regions:
        regions = tuple(region for region in org_regions if region in team_regions)
        if not regions:
            findings.append(config_finding("Team approved_regions excludes every organization region."))
    else:
        regions = org_regions or team_regions
    tags = tuple(dict.fromkeys((*org_tags, *team_tags)))
    extra = overlay.get("extra_rules_dir")
    if extra is not None and not isinstance(extra, str):
        raise ValueError("extra_rules_dir must be a project-relative directory")
    extra_dir = _safe_relative_dir(root, extra) if extra is not None else None
    active_ids = list(manifests["baseline"].rule_ids)
    for name in enabled:
        active_ids.extend(manifests[name].rule_ids)
    active_ids = list(dict.fromkeys(active_ids))
    active_ids = [rule_id for rule_id in active_ids
                  if rule_id in mandatory_ids or rule_id not in disabled]
    from .rules import load_rules

    current_severity = {rule.id: rule.severity.lower() for rule in load_rules(include_governance=True)}
    current_severity.update({"CFG001": "critical", "TEAM001": "high"})
    preliminary = TeamPolicy(root, regions, tags, owners, enabled, extra_dir,
                             {}, disabled, tuple(sorted(mandatory_ids)),
                             tuple(active_ids), tuple(findings))
    sources = _collect_external_sources(
        preliminary, package_root=package_root,
        existing_rule_ids=current_severity,
    )
    for rule_id, source in sources:
        severity = _literal_rule_severity(source, rule_id)
        if severity is not None:
            current_severity[rule_id] = severity
    raw_overrides = overlay.get("severity_overrides", {})
    if not isinstance(raw_overrides, dict):
        raise ValueError("severity_overrides must be a TOML table")
    overrides: dict[str, str] = {}
    for rule_id, severity in raw_overrides.items():
        if not isinstance(rule_id, str) or not _RULE_ID.fullmatch(rule_id):
            raise ValueError("severity_overrides contains an invalid rule ID")
        if not isinstance(severity, str) or severity.lower() not in _SEVERITY:
            raise ValueError(f"severity_overrides.{rule_id} needs low, medium, high, or critical")
        normalized = severity.lower()
        existing = current_severity.get(rule_id)
        if existing is None:
            findings.append(config_finding(f"Rule {rule_id} is unknown; its severity cannot be changed."))
        elif _SEVERITY[normalized] < _SEVERITY[existing]:
            findings.append(config_finding(f"Rule {rule_id} severity cannot be lowered from {existing}."))
        else:
            overrides[rule_id] = normalized
    return TeamPolicy(root, regions, tags, owners, enabled, extra_dir,
                      overrides, disabled, tuple(sorted(mandatory_ids)),
                      tuple(active_ids), tuple(findings))


def baseline_disable_findings(
    policy: TeamPolicy, disabled_rule_ids: Collection[str],
) -> tuple[RuleFinding, ...]:
    """Flag CLI attempts to bypass a mandatory rule without disabling it."""
    mandatory = set(policy.mandatory_rule_ids)
    return tuple(config_finding(f"Organization-mandated rule {rule_id} cannot be disabled.")
                 for rule_id in sorted(set(disabled_rule_ids) & mandatory))


def governance_settings(org_settings: Mapping[str, Any], policy: TeamPolicy) -> dict[str, Any]:
    """Return settings suitable for ``context_from_settings``."""
    merged = dict(org_settings)
    governance = dict(org_settings.get("governance", {}))
    governance["approved_regions"] = list(policy.approved_regions)
    governance["required_tags"] = list(policy.required_tags)
    merged["governance"] = governance
    return merged


def raise_findings(
    findings: Sequence[RuleFinding], policy: TeamPolicy,
) -> tuple[RuleFinding, ...]:
    """Apply severity increases, checking the actual finding at run time."""
    result: list[RuleFinding] = []
    for finding in findings:
        requested = policy.severity_overrides.get(finding.rule_id)
        if requested is None:
            result.append(finding)
            continue
        actual = _SEVERITY.get(finding.severity.lower())
        if actual is None or _SEVERITY[requested] < actual:
            result.append(finding)
            result.append(config_finding(
                f"Rule {finding.rule_id} severity cannot be lowered from {finding.severity}."))
        else:
            result.append(replace(finding, severity=requested))
    return tuple(result)


def owner_findings(changes: Sequence[Any], policy: TeamPolicy) -> tuple[RuleFinding, ...]:
    """Enforce optional approved owner-tag values in a team overlay."""
    if not policy.owners:
        return ()
    findings: list[RuleFinding] = []
    for change in changes:
        supports_tags = bool(change.tags) or any(
            isinstance(state, dict) and ("tags" in state or "tags_all" in state)
            for state in (change.before, change.after)
        )
        if (("delete" in change.actions and "create" not in change.actions)
                or not supports_tags):
            continue
        owner = change.tags.get("owner", "")
        if owner not in policy.owners:
            findings.append(RuleFinding(
                rule_id="TEAM001", resource=change.address,
                title="Owner outside team allowlist", severity="high",
                message=f"Owner tag {owner or '(missing)'} is not an approved team owner.",
                headline="Resource owner needs team approval",
                why_it_matters="The team must be able to identify who owns this change.",
                how_to_fix="Set the owner tag to a value listed in .argus/team.toml.",
            ))
    return tuple(findings)


def _rule_from_file(path: Path, expected_id: str) -> Any:
    """Import one project-local rule file with a unique private module name."""
    from .rules import Rule

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path}: rule file is missing or is a symlink")
    module_name = "_argus_team_" + sha256(str(path).encode("utf-8")).hexdigest()[:16]
    spec = spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{path}: cannot import rule")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    classes = [cls for _, cls in inspect.getmembers(module, inspect.isclass)
               if issubclass(cls, Rule) and cls is not Rule and cls.__module__ == module_name]
    if len(classes) != 1 or getattr(classes[0], "id", None) != expected_id:
        raise ValueError(f"{path}: expected exactly one Rule subclass with ID {expected_id}")
    return classes[0]()


def _collect_external_sources(
    policy: TeamPolicy, *, package_root: Path | None = None,
    existing_rule_ids: Collection[str] = (),
) -> tuple[tuple[str, Path], ...]:
    """Validate every external path and ID before importing any rule code."""
    source_root = (package_root or Path(__file__).resolve().parents[1]).resolve()
    manifests = load_packs(policy.root, package_root=source_root)
    existing = set(existing_rule_ids)
    seen = set(existing)
    sources: list[tuple[str, Path]] = []
    for pack_name in policy.enabled_packs:
        manifest = manifests[pack_name]
        for rule_id in manifest.rule_ids:
            if rule_id in policy.disabled_rules or rule_id in existing:
                continue
            candidates = (policy.root / "packs" / pack_name / "rules" / f"{rule_id.lower()}.py",
                          source_root / "packs" / pack_name / "rules" / f"{rule_id.lower()}.py",
                          Path(__file__).resolve().parent / "assets" / "packs" / pack_name
                          / "rules" / f"{rule_id.lower()}.py")
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None:
                raise ValueError(f"enabled pack {pack_name} has no implementation for {rule_id}")
            parent = path.parent
            bundled_root = Path(__file__).resolve().parent / "assets"
            if (parent.is_symlink() or path.is_symlink()
                    or not any(path.resolve().is_relative_to(allowed)
                               for allowed in (policy.root, source_root, bundled_root))):
                raise ValueError(f"{path}: pack rule escapes its root")
            if rule_id in seen:
                raise ValueError(f"duplicate deterministic rule ID: {rule_id}")
            seen.add(rule_id)
            sources.append((rule_id, path))
    if policy.extra_rules_dir is not None:
        directory = policy.extra_rules_dir
        if directory.is_symlink() or not directory.resolve().is_relative_to(policy.root):
            raise ValueError("extra_rules_dir must stay inside the project")
        if not directory.is_dir():
            raise ValueError(f"{directory}: extra_rules_dir does not exist")
        for path in sorted(directory.glob("*.py")):
            if path.name == "__init__.py":
                continue
            rule_id = path.stem.upper()
            if not _RULE_ID.fullmatch(rule_id):
                raise ValueError(f"{path}: invalid rule filename")
            if rule_id in seen:
                raise ValueError(f"duplicate deterministic rule ID: {rule_id}")
            if path.is_symlink() or not path.resolve().is_relative_to(policy.root):
                raise ValueError(f"{path}: team rule escapes its root")
            seen.add(rule_id)
            if rule_id in policy.disabled_rules:
                continue
            sources.append((rule_id, path))
    return tuple(sources)


def _literal_rule_severity(path: Path, rule_id: str) -> str | None:
    """Inspect a declared class severity without running its Python code."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        attributes: dict[str, str] = {}
        for item in node.body:
            if (isinstance(item, ast.Assign) and len(item.targets) == 1
                    and isinstance(item.targets[0], ast.Name)
                    and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)):
                attributes[item.targets[0].id] = item.value.value
        if attributes.get("id") == rule_id:
            severity = attributes.get("severity", "").lower()
            return severity if severity in _SEVERITY else None
    return None


def load_extra_rules(
    policy: TeamPolicy, *, package_root: Path | None = None,
    existing_rule_ids: Collection[str] = (),
) -> tuple[Any, ...]:
    """Load external rules after validating all paths and duplicate IDs.

    Pass all built-in rule IDs as ``existing_rule_ids``. A promoted pack rule
    may remain in ``argus/rules``; the built-in copy runs once when that pack is
    enabled. A team extra rule may never shadow a built-in or pack rule.
    """
    sources = _collect_external_sources(
        policy, package_root=package_root, existing_rule_ids=existing_rule_ids,
    )
    return tuple(_rule_from_file(path, rule_id) for rule_id, path in sources)


def init_team(root: Path) -> Path:
    """Create a commented team overlay, refusing to overwrite existing work."""
    root = root.resolve()
    directory = root / ".argus"
    if directory.is_symlink():
        raise ValueError(".argus may not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "team.toml"
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"{path} already exists")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(_INIT_TEXT)
    return path


def _validate_promotion_tests(path: Path) -> None:
    """Require two pytest-style tests with assertions before a rule copy."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        raise ValueError(f"{path}: test file has invalid Python syntax") from error
    tests = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name.startswith("test_")]
    if len(tests) < 2 or any(
        not any(isinstance(child, ast.Assert) for child in ast.walk(test))
        for test in tests
    ):
        raise ValueError(f"{path}: promotion needs at least two test_* functions with assertions")


def promote_rule(
    root: Path, rule_id: str, *, source_dir: Path | None = None,
    sync_assets: bool | None = None,
) -> tuple[Path, Path]:
    """Copy one reviewed team rule and its test into the AWS core pack.

    The caller prints the returned paths and the mandatory human review
    checklist; this function only copies validated project-local files.
    """
    if not _RULE_ID.fullmatch(rule_id):
        raise ValueError("invalid rule ID")
    root = root.resolve()
    policy = load_team_policy(root, {})
    source_dir = source_dir or policy.extra_rules_dir or root / "argus" / "rules"
    if source_dir.is_symlink():
        raise ValueError("rule source may not be a symlink")
    source_dir = source_dir.resolve()
    if not source_dir.is_relative_to(root):
        raise ValueError("rule source must stay inside the project")
    stem = rule_id.lower()
    source = source_dir / f"{stem}.py"
    test_candidates = (source_dir.parent / "tests" / f"test_{stem}.py",
                       root / "tests" / "rules" / f"test_{stem}.py")
    test = next((candidate for candidate in test_candidates if candidate.is_file()), None)
    if not source.is_file() or source.is_symlink() or test is None or test.is_symlink():
        raise ValueError(f"{rule_id} needs a project-local rule and matching test")
    if not test.resolve().is_relative_to(root):
        raise ValueError("rule test must stay inside the project")
    _validate_promotion_tests(test)
    pack_dir = root / "packs" / "aws-core"
    if ((root / "packs").is_symlink() or pack_dir.is_symlink()
            or not pack_dir.resolve().is_relative_to(root)):
        raise ValueError("pack destination must stay inside the project")
    manifest_path = pack_dir / "pack.toml"
    if manifest_path.is_symlink():
        raise ValueError("pack manifest may not be a symlink")
    if not manifest_path.is_file():
        bundled = Path(__file__).resolve().parent / "assets" / "packs" / "aws-core" / "pack.toml"
        pack_dir.mkdir(parents=True, exist_ok=True)
        with manifest_path.open("x", encoding="utf-8") as stream:
            stream.write(bundled.read_text(encoding="utf-8"))
    manifest = _read_manifest(manifest_path, "aws-core")
    if rule_id in manifest.rule_ids:
        raise FileExistsError(f"{rule_id} is already in aws-core")
    rule_target = pack_dir / "rules" / source.name
    test_target = pack_dir / "tests" / test.name
    for directory in (rule_target.parent, test_target.parent):
        if directory.is_symlink() or not directory.resolve().is_relative_to(root):
            raise ValueError("pack destination must stay inside the project")
    if rule_target.exists() or test_target.exists() or rule_target.is_symlink() or test_target.is_symlink():
        raise FileExistsError(f"destination for {rule_id} already exists")
    if sync_assets is None:
        sync_assets = (root == Path(__file__).resolve().parents[1].resolve()
                       and (root / ".git").is_dir())
    asset_rule: Path | None = None
    asset_manifest: Path | None = None
    old_asset_manifest: bytes | None = None
    if sync_assets:
        asset_pack = root / "argus" / "assets" / "packs" / "aws-core"
        asset_rule = asset_pack / "rules" / source.name
        asset_manifest = asset_pack / "pack.toml"
        if (not asset_manifest.is_file() or asset_manifest.is_symlink()
                or asset_rule.parent.is_symlink() or asset_rule.exists()
                or asset_rule.is_symlink()
                or not asset_rule.resolve().is_relative_to(root)):
            raise ValueError("bundled aws-core asset destination is unsafe or incomplete")
        old_asset_manifest = asset_manifest.read_bytes()
    rule_target.parent.mkdir(parents=True, exist_ok=True)
    test_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, rule_target)
    shutil.copy2(test, test_target)
    raw = manifest_path.read_text(encoding="utf-8")
    replacement = "rule_ids = [" + ", ".join(f'"{item}"' for item in (*manifest.rule_ids, rule_id)) + "]"
    updated, count = re.subn(r"(?m)^rule_ids\s*=\s*\[[^\]]*\]", replacement, raw, count=1)
    if count != 1:
        rule_target.unlink()
        test_target.unlink()
        raise ValueError("aws-core manifest must have a one-line rule_ids list")
    try:
        manifest_path.write_text(updated, encoding="utf-8")
        if asset_rule is not None and asset_manifest is not None:
            asset_rule.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rule_target, asset_rule)
            asset_manifest.write_bytes(manifest_path.read_bytes())
    except Exception:
        manifest_path.write_text(raw, encoding="utf-8")
        rule_target.unlink(missing_ok=True)
        test_target.unlink(missing_ok=True)
        if asset_rule is not None:
            asset_rule.unlink(missing_ok=True)
        if asset_manifest is not None and old_asset_manifest is not None:
            asset_manifest.write_bytes(old_asset_manifest)
        raise
    return rule_target, test_target
