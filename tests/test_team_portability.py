"""Phase 19 team overlays, pack promotion, and installed-package assets."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from zipfile import ZipFile
import json
import os

import pytest

from argus import cli
from argus.governance import context_from_settings
from argus.models import Change, RuleFinding
from argus.parse_plan import parse_plan
from argus.rules import load_rules, run_rules
from argus.team import (baseline_disable_findings, governance_settings, init_team, load_extra_rules,
                        load_packs, load_team_policy, owner_findings,
                        promote_rule, raise_findings)
from argus.verdict import decide_verdict


ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "fixtures" / "plans" / "clean_change.json"


def _overlay(root: Path, content: str) -> None:
    path = root / ".argus" / "team.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _enabled_project(root: Path, overlay: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "argus.toml").write_text(
        "[flags]\nteam_overlays = true\ngovernance_pack = false\n",
        encoding="utf-8",
    )
    _overlay(root, overlay)


def _last_ids(root: Path) -> set[str]:
    record = json.loads((root / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    return {item["rule_id"] for item in record["rule_findings"]}


def test_pack_manifests_keep_baseline_explicit() -> None:
    manifests = load_packs(ROOT)
    assert tuple(manifests) == ("baseline", "aws-core", "governance")
    assert manifests["baseline"].rule_ids == (
        *tuple(f"R{n:03d}" for n in range(1, 8)), "W001")
    assert "G21" in manifests["governance"].rule_ids
    assert all(manifest.version and manifest.owner and manifest.description
               for manifest in manifests.values())


def test_team_workspace_cannot_shadow_bundled_baseline_manifest(tmp_path: Path) -> None:
    path = tmp_path / "packs" / "baseline" / "pack.toml"
    path.parent.mkdir(parents=True)
    path.write_text('name = "baseline"\nversion = "9"\nowner = "team"\n'
                    'description = "unsafe"\nrule_ids = []\n', encoding="utf-8")
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    assert "R001" in policy.active_rule_ids
    assert "W001" in policy.active_rule_ids


def test_init_creates_commented_overlay_without_overwriting(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    path = tmp_path / ".argus" / "team.toml"
    assert path == tmp_path / ".argus" / "team.toml"
    assert "# The organization baseline is always enabled" in path.read_text(encoding="utf-8")
    assert tomllib.loads(path.read_text(encoding="utf-8"))["enabled_packs"] == ["aws-core"]
    assert [item for item in tmp_path.rglob("*") if item.is_file()] == [path]
    with pytest.raises(FileExistsError):
        init_team(tmp_path)


def test_team_examples_give_different_verdicts_on_same_plan() -> None:
    changes = parse_plan(CLEAN)
    org = {"governance": {"required_tags": ["env"]}, "flags": {"governance_pack": False}}
    verdicts = []
    for name in ("team-analytics", "team-payments"):
        example_settings = tomllib.loads(
            (ROOT / "examples" / name / "argus.toml").read_text(encoding="utf-8"))
        assert example_settings["flags"]["team_overlays"] is True
        policy = load_team_policy(ROOT / "examples" / name, org, package_root=ROOT)
        assert not policy.findings
        assert "R001" in policy.active_rule_ids and "G21" in policy.active_rule_ids
        context = context_from_settings(governance_settings(org, policy))
        findings = run_rules(changes, include_governance=True, governance_context=context,
                             controls_path=ROOT / "controls.yaml")
        verdicts.append(decide_verdict(findings))
    assert verdicts == ["GO", "NO-GO"]


def test_cli_team_examples_differ_on_same_plan(tmp_path: Path, monkeypatch) -> None:
    results = []
    for name in ("team-analytics", "team-payments"):
        root = tmp_path / name
        overlay = (ROOT / "examples" / name / ".argus" / "team.toml").read_text(encoding="utf-8")
        _enabled_project(root, overlay)
        monkeypatch.setattr(cli, "PROJECT_ROOT", root)
        results.append((cli.run_check(CLEAN, emit_output=False), _last_ids(root)))
    assert results[0][0] == 0
    assert "G21" not in results[0][1]
    assert results[1][0] == 1
    assert "G21" in results[1][1]


def test_source_checkout_commands_use_each_example_working_directory(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT)
    environment["PYTHONNOUSERSITE"] = "1"
    for name, expected_code in (("team-analytics", 0), ("team-payments", 1)):
        example = tmp_path / name
        shutil.copytree(ROOT / "examples" / name, example)
        result = subprocess.run(
            [sys.executable, "-m", "argus", "check", str(CLEAN)],
            cwd=example, env=environment, capture_output=True, text=True, check=False,
        )
        assert result.returncode == expected_code, result.stderr or result.stdout
        assert (example / "ledger" / "ledger.jsonl").is_file()
        assert (example / "reports" / "latest.md").is_file()
        assert ("G21" in _last_ids(example)) is (name == "team-payments")


def test_cli_baseline_disable_still_evaluates_r001_and_w001(tmp_path: Path, monkeypatch) -> None:
    _enabled_project(tmp_path, 'enabled_packs = ["aws-core"]\n')
    (tmp_path / "agents.yaml").write_bytes((ROOT / "agents.yaml").read_bytes())
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    act1 = ROOT / "fixtures" / "plans" / "act1_replace_pii_db.json"
    assert cli.run_check(act1, disabled_rules=("R001",), emit_output=False) == 1
    assert {"R001", "CFG001"} <= _last_ids(tmp_path)
    assert cli.run_check(CLEAN, disabled_rules=("W001",), author="agent:landing-zone",
                         changed_files=("argus/rules/r007.py",), emit_output=False) == 1
    assert {"W001", "CFG001"} <= _last_ids(tmp_path)


def test_cli_executes_team_extra_rules(tmp_path: Path, monkeypatch) -> None:
    _enabled_project(tmp_path, 'enabled_packs = []\nextra_rules_dir = ".argus/rules"\n')
    directory = tmp_path / ".argus" / "rules"
    directory.mkdir()
    (directory / "t001.py").write_text(
        'from argus.rules import Rule\n'
        'class TeamSample(Rule):\n'
        '    id = "T001"\n    title = "Synthetic sample"\n    severity = "high"\n'
        '    why_it_matters = "Synthetic reason."\n'
        '    how_to_fix = "Synthetic fix."\n'
        '    def check(self, change, all_changes):\n'
        '        return [self.finding(change, "Synthetic team rule triggered.")]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.run_check(CLEAN, emit_output=False) == 1
    assert "T001" in _last_ids(tmp_path)


def test_cli_ignores_tampered_local_governance_manifest(tmp_path: Path, monkeypatch) -> None:
    _enabled_project(tmp_path, 'required_tags = ["cost_center"]\nenabled_packs = []\n')
    (tmp_path / "argus.toml").write_text(
        "[flags]\nteam_overlays = true\ngovernance_pack = true\n", encoding="utf-8")
    local_manifest = tmp_path / "packs" / "governance" / "pack.toml"
    local_manifest.parent.mkdir(parents=True)
    local_manifest.write_text('name = "governance"\nversion = "9"\nowner = "team"\n'
                              'description = "unsafe"\nrule_ids = []\n', encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    policy = load_team_policy(tmp_path, cli._settings())
    assert "G21" in policy.mandatory_rule_ids
    assert "G21" in policy.active_rule_ids
    assert cli.run_check(CLEAN, emit_output=False) == 1
    assert "G21" in _last_ids(tmp_path)


def test_cli_overlay_cannot_disable_org_mandated_g21(tmp_path: Path, monkeypatch) -> None:
    _enabled_project(tmp_path, 'required_tags = ["cost_center"]\n'
                     'disabled_rules = ["G21"]\nenabled_packs = []\n')
    (tmp_path / "argus.toml").write_text(
        "[flags]\nteam_overlays = true\ngovernance_pack = true\n", encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.run_check(CLEAN, emit_output=False) == 1
    assert {"G21", "CFG001"} <= _last_ids(tmp_path)


def test_required_tags_auto_activate_governance_from_default_overlay(
    tmp_path: Path, monkeypatch,
) -> None:
    _enabled_project(tmp_path, 'required_tags = ["cost_center"]\n'
                     'enabled_packs = ["aws-core"]\n')
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.run_check(CLEAN, emit_output=False) == 1
    assert "G21" in _last_ids(tmp_path)


def test_org_thresholds_auto_activate_governance_pack(tmp_path: Path) -> None:
    _overlay(tmp_path, 'enabled_packs = []\n')
    org = {"flags": {"governance_pack": False},
           "governance": {"allowed_instance_classes": ["synthetic.large"],
                          "minimum_retention_days": 10}}
    policy = load_team_policy(tmp_path, org, package_root=ROOT)
    assert "governance" in policy.enabled_packs
    assert {"G17", "G23"} <= set(policy.mandatory_rule_ids)


def test_baseline_disable_and_severity_reduction_become_critical_findings(tmp_path: Path) -> None:
    _overlay(tmp_path, 'disabled_rules = ["R001"]\n[severity_overrides]\nR001 = "low"\n')
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    assert "R001" in policy.active_rule_ids
    assert "R001" not in policy.severity_overrides
    assert len(policy.findings) == 2
    assert all(finding.rule_id == "CFG001" and finding.severity == "critical"
               for finding in policy.findings)
    assert decide_verdict(policy.findings) == "NO-GO"
    cli_attempts = baseline_disable_findings(policy, ("R001", "W001", "G21"))
    assert len(cli_attempts) == 2
    assert all(item.rule_id == "CFG001" for item in cli_attempts)
    assert any("W001" in item.message for item in cli_attempts)


def test_config_and_owner_severity_cannot_be_lowered_or_hidden(tmp_path: Path) -> None:
    _overlay(tmp_path, '[severity_overrides]\nCFG001 = "low"\nTEAM001 = "low"\nT999 = "low"\n')
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    assert not policy.severity_overrides
    assert len(policy.findings) == 3
    assert all(finding.severity == "critical" for finding in policy.findings)
    assert raise_findings(policy.findings, policy) == policy.findings


def test_team_rule_severity_can_be_raised(tmp_path: Path) -> None:
    directory = tmp_path / ".argus" / "rules"
    directory.mkdir(parents=True)
    (directory / "t001.py").write_text(
        'from argus.rules import Rule\n'
        'class TeamSample(Rule):\n'
        '    id = "T001"\n    title = "Synthetic sample"\n    severity = "low"\n'
        '    why_it_matters = "Synthetic reason."\n'
        '    how_to_fix = "Synthetic fix."\n'
        '    def check(self, change, all_changes):\n'
        '        return [self.finding(change, "Synthetic low finding.")]\n',
        encoding="utf-8",
    )
    _overlay(tmp_path, 'extra_rules_dir = ".argus/rules"\n'
             '[severity_overrides]\nT001 = "high"\n')
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    assert policy.severity_overrides["T001"] == "high"
    rules = load_extra_rules(policy, package_root=ROOT,
                             existing_rule_ids={rule.id for rule in load_rules(include_governance=True)})
    finding = rules[0].check(parse_plan(CLEAN)[0], parse_plan(CLEAN))[0]
    raised = raise_findings((finding,), policy)
    assert len(raised) == 1 and raised[0].severity == "high"


def test_runtime_severity_floor_catches_misleading_first_class(tmp_path: Path) -> None:
    directory = tmp_path / ".argus" / "rules"
    directory.mkdir(parents=True)
    (directory / "t001.py").write_text(
        'class Dummy:\n    id = "T001"\n    severity = "low"\n'
        'from argus.rules import Rule\n'
        'class Actual(Rule):\n'
        '    id = "T001"\n    title = "Actual high risk"\n    severity = "high"\n'
        '    why_it_matters = "Synthetic reason."\n'
        '    how_to_fix = "Synthetic fix."\n'
        '    def check(self, change, all_changes):\n'
        '        return [self.finding(change, "Actual high finding.")]\n',
        encoding="utf-8",
    )
    _overlay(tmp_path, 'extra_rules_dir = ".argus/rules"\n'
             '[severity_overrides]\nT001 = "medium"\n')
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    assert policy.severity_overrides["T001"] == "medium"
    rules = load_extra_rules(policy, package_root=ROOT,
                             existing_rule_ids={rule.id for rule in load_rules(include_governance=True)})
    finding = rules[0].check(parse_plan(CLEAN)[0], parse_plan(CLEAN))[0]
    guarded = raise_findings((finding,), policy)
    assert [item.rule_id for item in guarded] == ["T001", "CFG001"]
    assert guarded[0].severity == "high" and guarded[1].severity == "critical"


def test_team_adds_constraints_without_erasing_org_policy(tmp_path: Path) -> None:
    _overlay(tmp_path, 'required_tags = ["cost_center"]\napproved_regions = ["synthetic-east"]\n'
             'enabled_packs = []\n[severity_overrides]\nR002 = "critical"\n')
    org = {"governance": {"required_tags": ["env"],
                          "approved_regions": ["synthetic-east", "synthetic-west"]},
           "flags": {"governance_pack": True}}
    policy = load_team_policy(tmp_path, org, package_root=ROOT)
    assert policy.required_tags == ("env", "cost_center")
    assert policy.approved_regions == ("synthetic-east",)
    assert policy.enabled_packs == ("governance",)
    assert "G21" in policy.active_rule_ids
    finding = RuleFinding("R002", "synthetic", "Sample", "high", "Sample")
    assert raise_findings((finding,), policy)[0].severity == "critical"


def test_disjoint_regions_and_traversal_fail_closed(tmp_path: Path) -> None:
    _overlay(tmp_path, 'approved_regions = ["synthetic-west"]\n')
    policy = load_team_policy(tmp_path,
                              {"governance": {"approved_regions": ["synthetic-east"]}},
                              package_root=ROOT)
    assert policy.approved_regions == ()
    assert any(item.rule_id == "CFG001" for item in policy.findings)
    _overlay(tmp_path, 'extra_rules_dir = "../outside"\n')
    with pytest.raises(ValueError, match="project-relative"):
        load_team_policy(tmp_path, {}, package_root=ROOT)


def test_owner_check_skips_untaggable_resources(tmp_path: Path) -> None:
    _overlay(tmp_path, 'owners = ["approved-synthetic-team"]\n')
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    tagged = parse_plan(CLEAN)[0]
    untaggable = replace(tagged, address="aws_security_group_rule.synthetic",
                         before={"from_port": 22}, after={"from_port": 443}, tags={})
    findings = owner_findings((tagged, untaggable), policy)
    assert len(findings) == 1
    assert findings[0].resource == tagged.address
    assert findings[0].rule_id == "TEAM001"


def test_promotion_copies_rule_and_test_then_loads_pack_module(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "argus.toml").write_text(
        "[flags]\nteam_overlays = true\n", encoding="utf-8")
    rule_dir = tmp_path / "argus" / "rules"
    test_dir = tmp_path / "tests" / "rules"
    rule_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (rule_dir / "t001.py").write_text(
        'from argus.rules import Rule\n'
        'class TeamSample(Rule):\n'
        '    id = "T001"\n    title = "Synthetic sample"\n    severity = "high"\n'
        '    why_it_matters = "Synthetic reason."\n'
        '    how_to_fix = "Synthetic fix."\n'
        '    def check(self, change, all_changes):\n        return []\n',
        encoding="utf-8",
    )
    (test_dir / "test_t001.py").write_text(
        "def test_triggering_case():\n    assert True\n\n"
        "def test_non_triggering_case():\n    assert True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    assert cli.main(["promote", "T001"]) == 0
    targets = (tmp_path / "packs" / "aws-core" / "rules" / "t001.py",
               tmp_path / "packs" / "aws-core" / "tests" / "test_t001.py")
    assert all(path.is_file() for path in targets)
    assert (tmp_path / "packs" / "aws-core" / "pack.toml").is_file()
    policy = load_team_policy(tmp_path, {}, package_root=ROOT)
    assert "T001" in policy.active_rule_ids
    existing = {rule.id for rule in load_rules(include_governance=True)}
    loaded = load_extra_rules(policy, package_root=ROOT, existing_rule_ids=existing)
    assert [rule.id for rule in loaded] == ["T001"]
    with pytest.raises(FileExistsError):
        promote_rule(tmp_path, "T001")


def test_promotion_rejects_comment_only_test_file(tmp_path: Path) -> None:
    rule_dir = tmp_path / "argus" / "rules"
    test_dir = tmp_path / "tests" / "rules"
    rule_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (rule_dir / "t001.py").write_text("# Synthetic rule source.\n", encoding="utf-8")
    (test_dir / "test_t001.py").write_text("# No collected tests.\n", encoding="utf-8")
    with pytest.raises(ValueError, match="two test_"):
        promote_rule(tmp_path, "T001")
    assert not (tmp_path / "packs").exists()


def test_team_extra_rule_may_not_shadow_builtin(tmp_path: Path) -> None:
    directory = tmp_path / ".argus" / "rules"
    directory.mkdir(parents=True)
    (directory / "r001.py").write_text("# duplicate source\n", encoding="utf-8")
    _overlay(tmp_path, 'extra_rules_dir = ".argus/rules"\n')
    with pytest.raises(ValueError, match="duplicate"):
        load_team_policy(tmp_path, {}, package_root=ROOT)


def test_ci_templates_run_argus_check_without_masking_failure() -> None:
    for name in ("github-actions.yml", "azure-pipelines.yml", "gitlab-ci.yml"):
        content = (ROOT / "templates" / "ci" / name).read_text(encoding="utf-8")
        assert "argus check" in content
        assert "|| true" not in content and "continue-on-error" not in content


def test_wheel_bundles_byte_identical_policy_and_schema_defaults(tmp_path: Path) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["argus"] == "argus.cli:main"
    source = tmp_path / "source"
    source.mkdir()
    shutil.copytree(ROOT / "argus", source / "argus",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", source / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", source / "README.md")
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--wheel-dir", str(tmp_path), str(source)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    wheels = list(tmp_path.glob("argus_infra_gate-*.whl"))
    assert len(wheels) == 1
    with ZipFile(wheels[0]) as wheel:
        for name in ("permissions.yaml", "exceptions.yaml", "controls.yaml"):
            bundled = wheel.read(f"argus/assets/{name}")
            assert bundled == (ROOT / name).read_bytes()
        assert wheel.read("argus/assets/schemas/finding.schema.json") == (
            ROOT / "schemas" / "finding.schema.json").read_bytes()
        for name in ("baseline", "aws-core", "governance"):
            assert wheel.read(f"argus/assets/packs/{name}/pack.toml") == (
                ROOT / "packs" / name / "pack.toml").read_bytes()

    installed = tmp_path / "installed"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--target", str(installed), str(wheels[0])],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert install.returncode == 0, install.stderr
    team_root = tmp_path / "synthetic-team"
    _enabled_project(team_root, 'required_tags = ["env", "owner"]\n'
                     'enabled_packs = ["governance"]\n')
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(installed)
    environment["PYTHONNOUSERSITE"] = "1"
    probe = subprocess.run(
        [sys.executable, "-c", "import argus; print(argus.__file__)"],
        cwd=team_root, env=environment, capture_output=True, text=True, check=False,
    )
    assert probe.returncode == 0, probe.stderr
    assert Path(probe.stdout.strip()).resolve().is_relative_to(installed)
    check = subprocess.run(
        [sys.executable, "-m", "argus", "check", str(CLEAN)],
        cwd=team_root, env=environment, capture_output=True, text=True, check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout
    assert (team_root / "ledger" / "ledger.jsonl").is_file()
    assert (team_root / "reports" / "latest.md").is_file()
    assert not (installed / "ledger").exists()


def test_central_promotion_is_available_in_a_newly_built_wheel(tmp_path: Path) -> None:
    source = tmp_path / "central"
    source.mkdir()
    shutil.copytree(ROOT / "argus", source / "argus",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", source / "pyproject.toml")
    shutil.copy2(ROOT / "README.md", source / "README.md")
    pack = source / "packs" / "aws-core"
    pack.mkdir(parents=True)
    shutil.copy2(ROOT / "packs" / "aws-core" / "pack.toml", pack / "pack.toml")
    rule_dir = source / "argus" / "rules"
    test_dir = source / "tests" / "rules"
    test_dir.mkdir(parents=True)
    (rule_dir / "t001.py").write_text(
        'from argus.rules import Rule\n'
        'class TeamSample(Rule):\n'
        '    id = "T001"\n    title = "Synthetic promotion rule"\n'
        '    severity = "high"\n    why_it_matters = "Synthetic reason."\n'
        '    how_to_fix = "Synthetic fix."\n'
        '    def check(self, change, all_changes):\n'
        '        if change.tags.get("env") == "dev":\n'
        '            return [self.finding(change, "Synthetic dev finding.")]\n'
        '        return []\n',
        encoding="utf-8",
    )
    (test_dir / "test_t001.py").write_text(
        'from argus.models import Change\nfrom argus.rules.t001 import TeamSample\n'
        'def _change(env):\n'
        '    return Change("synthetic", "aws_instance", "compute_instance", '
        '("update",), {}, {}, (), {"env": env}, False)\n'
        'def test_triggering_case():\n'
        '    change = _change("dev")\n'
        '    assert TeamSample().check(change, (change,))\n'
        'def test_non_triggering_case():\n'
        '    change = _change("prod")\n'
        '    assert not TeamSample().check(change, (change,))\n',
        encoding="utf-8",
    )
    promote_rule(source, "T001", sync_assets=True)
    bundled_pack = source / "argus" / "assets" / "packs" / "aws-core"
    assert (bundled_pack / "rules" / "t001.py").is_file()
    assert "T001" in tomllib.loads((bundled_pack / "pack.toml").read_text(
        encoding="utf-8"))["rule_ids"]
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--wheel-dir", str(wheel_dir), str(source)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert build.returncode == 0, build.stderr
    wheel = next(wheel_dir.glob("argus_infra_gate-*.whl"))
    with ZipFile(wheel) as archive:
        assert "T001" in archive.read("argus/assets/packs/aws-core/pack.toml").decode("utf-8")
        assert archive.read("argus/assets/packs/aws-core/rules/t001.py") == (
            bundled_pack / "rules" / "t001.py").read_bytes()
    installed = tmp_path / "installed"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--target", str(installed), str(wheel)],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert install.returncode == 0, install.stderr
    team_root = tmp_path / "team"
    _enabled_project(team_root, 'enabled_packs = ["aws-core"]\n')
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(installed)
    environment["PYTHONNOUSERSITE"] = "1"
    run = subprocess.run(
        [sys.executable, "-m", "argus", "check", str(CLEAN)],
        cwd=team_root, env=environment, capture_output=True, text=True, check=False,
    )
    assert run.returncode == 1, run.stderr or run.stdout
    assert "T001" in _last_ids(team_root)
