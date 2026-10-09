"""Provider upgrades use configured arguments and locally verified guide quotes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from argus import cli, mcp_server, scholar
from argus.corpus import load_corpus
from argus.upgrade import (GUIDE_ID, GUIDE_QUOTE, UpgradeSpec, collect_upgrade_changes,
                           resolve_upgrade)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "upgrades" / "aws_v4_to_v5" / "plan.json"
SPEC = UpgradeSpec("aws", "4.67.0", "5.0.0")


def _project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)
    for name in ("permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    (tmp_path / "argus.toml").write_text('[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / f"{GUIDE_ID}.md").write_bytes((ROOT / "corpus" / f"{GUIDE_ID}.md").read_bytes())
    plan = tmp_path / "plan.json"
    plan.write_bytes(FIXTURE.read_bytes())
    return plan


def _model(monkeypatch, *, quote: str = GUIDE_QUOTE, fail: bool = False) -> None:
    def create(**kwargs):
        if fail:
            raise RuntimeError("synthetic Scholar failure")
        change = json.loads(kwargs["input"][0]["content"].removeprefix("CHANGE: "))
        return SimpleNamespace(output=[], output_text=json.dumps({"findings": [{
            "id": "F8", "resource": change["address"],
            "change_type": "provider_upgrade_breaking_argument",
            "claim": "Configured name is removed in provider v5.",
            "evidence": [{"doc_id": GUIDE_ID, "quote": quote}],
            "severity": "high", "recommended_action": "Replace name with db_name.",
            "confidence": "high",
        }]}))

    monkeypatch.setattr(scholar, "_live_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create)))


def test_collects_only_used_arguments_on_affected_resource_types(tmp_path: Path) -> None:
    guide = load_corpus(ROOT / "corpus")[GUIDE_ID]
    assert GUIDE_QUOTE in guide.body
    changes = collect_upgrade_changes(FIXTURE, SPEC, guide)
    assert len(changes) == 1
    change = changes[0]
    assert change.resource_type == "aws_db_instance"
    assert change.canonical_type == "provider-upgrade" and change.source_tool == "terraform"
    assert (change.provider, change.from_version, change.to_version) == ("aws", "4.67.0", "5.0.0")
    assert "name" in change.arguments_used and "bucket" not in change.arguments_used

    plan = json.loads(FIXTURE.read_text(encoding="utf-8"))
    database = next(item for item in plan["configuration"]["root_module"]["resources"]
                    if item["type"] == "aws_db_instance")
    del database["expressions"]["name"]
    database["expressions"]["db_name"] = {"constant_value": "orders"}
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(plan), encoding="utf-8")
    assert collect_upgrade_changes(clean, SPEC, guide) == ()


def test_versions_can_come_from_lock_files(tmp_path: Path) -> None:
    before = tmp_path / "before.lock.hcl"
    after = tmp_path / "after.lock.hcl"
    before.write_text('provider "registry.terraform.io/hashicorp/aws" {\n  version = "4.67.0"\n}', encoding="utf-8")
    after.write_text('provider "registry.terraform.io/hashicorp/aws" {\n  version = "5.0.0"\n}', encoding="utf-8")
    assert resolve_upgrade("aws", None, None, before, after) == SPEC
    with pytest.raises(ValueError, match="provide --from and --to"):
        resolve_upgrade("aws", "4.67.0", "5.0.0", before, after)


def test_cli_accepts_lock_file_pair(tmp_path: Path, monkeypatch) -> None:
    plan = _project(tmp_path, monkeypatch)
    before = tmp_path / "before.lock.hcl"
    after = tmp_path / "after.lock.hcl"
    before.write_text('provider "registry.terraform.io/hashicorp/aws" { version = "4.67.0" }', encoding="utf-8")
    after.write_text('provider "registry.terraform.io/hashicorp/aws" { version = "5.0.0" }', encoding="utf-8")
    _model(monkeypatch)
    assert cli.main(["upgrade-check", str(plan), "--provider", "aws",
                     "--lock-before", str(before), "--lock-after", str(after), "--live"]) == 1


def test_verified_breaking_quote_blocks_and_unverified_quote_does_not(tmp_path: Path, monkeypatch) -> None:
    plan = _project(tmp_path, monkeypatch)
    _model(monkeypatch)
    assert cli.run_check(plan, scholar_mode="live", upgrade=SPEC, emit_output=False,
                         governance_enabled=False, team_enabled=False) == 1
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert record["verdict"] == "NO-GO" and record["ai_findings"][0]["verified"] is True
    assert record["ai_findings"][0]["evidence"][0]["quote"] == GUIDE_QUOTE
    assert "AI findings are advisory" not in (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")

    _model(monkeypatch, quote="This sentence is long enough for verification but is absent from the vendor guide.")
    assert cli.run_check(plan, scholar_mode="live", upgrade=SPEC, emit_output=False,
                         governance_enabled=False, team_enabled=False) == 0
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert record["verdict"] == "GO"
    assert record["ai_findings"][0]["verified"] is False
    assert record["ai_findings"][0]["verification_reason"] == "quote_not_found"


def test_scholar_failure_holds_and_unaffected_config_skips_research(tmp_path: Path, monkeypatch) -> None:
    plan = _project(tmp_path, monkeypatch)
    _model(monkeypatch, fail=True)
    assert cli.run_check(plan, scholar_mode="live", upgrade=SPEC, emit_output=False,
                         governance_enabled=False, team_enabled=False) == 2
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert record["verdict"] == "NEEDS HUMAN"
    assert "HOLD FOR REVIEW" in (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")

    source = json.loads(plan.read_text(encoding="utf-8"))
    source["configuration"]["root_module"]["resources"] = [item for item in
        source["configuration"]["root_module"]["resources"] if item["type"] == "aws_s3_bucket"]
    plan.write_text(json.dumps(source), encoding="utf-8")
    assert cli.run_check(plan, scholar_mode="live", upgrade=SPEC, emit_output=False,
                         governance_enabled=False, team_enabled=False) == 0
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert record["ai_findings"] == []


def test_mcp_upgrade_tool_preserves_read_only_result_shape(tmp_path: Path, monkeypatch) -> None:
    _project(tmp_path, monkeypatch)
    _model(monkeypatch)
    outcome = mcp_server.argus_upgrade_check("plan.json", "aws", "4.67.0", "5.0.0", live=True)
    assert outcome["verdict"] == "NO-GO" and outcome["upgrade"]["provider"] == "aws"
    assert outcome["findings"][0]["verified"] is True
    assert (tmp_path / "ledger" / "runs" / f"{outcome['run_id']}.json").is_file()
    assert '"tool": "argus_upgrade_check"' in (tmp_path / "ledger" / "ledger.jsonl").read_text(encoding="utf-8")
