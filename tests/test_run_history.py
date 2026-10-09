"""Durable check history and demo replay stay inside the test workspace."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from argus import cli, scholar, smith
from argus.models import AIFinding


ROOT = Path(__file__).resolve().parents[1]
ACT2 = ROOT / "fixtures" / "plans" / "act2_major_upgrade.json"
ACT3 = ROOT / "fixtures" / "plans" / "act3_major_upgrade_second.json"


def _project(root: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", root)
    (root / "argus.toml").write_text(
        '[scholar]\nmodel = "gpt-6.1-sol"\n[smith]\ncodex_executable = "codex"\n',
        encoding="utf-8",
    )
    (root / "corpus").mkdir()
    for name in ("permissions.yaml", "exceptions.yaml"):
        (root / name).write_bytes((ROOT / name).read_bytes())


def _finding() -> AIFinding:
    return AIFinding(
        id="F1", resource="aws_db_instance.orders", change_type="update",
        claim="Synthetic concern", severity="high",
        recommended_action="Use the matching group.", verified=True,
        evidence=(), confidence="high",
    )


def test_checks_save_distinct_runs_and_print_ids(tmp_path: Path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch)
    assert cli.run_check(ACT3) == 1
    first = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert f"Run ID: {first['run_id']}" in capsys.readouterr().out
    assert first["rule_findings"][0]["rule_id"] == "R007"
    assert cli.run_check(ACT3, disabled_rules=("R007",)) == 0
    second = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert f"Run ID: {second['run_id']}" in capsys.readouterr().out
    assert second["rule_findings"] == []
    assert second["disabled_rules"] == ["R007"]
    saved = tmp_path / "ledger" / "runs"
    assert first["run_id"] != second["run_id"]
    assert json.loads((saved / f"{first['run_id']}.json").read_text(encoding="utf-8")) == first
    assert json.loads((saved / f"{second['run_id']}.json").read_text(encoding="utf-8")) == second


def test_compile_chooses_matching_run_or_explicit_run(tmp_path: Path, monkeypatch, capsys) -> None:
    _project(tmp_path, monkeypatch)
    runs = tmp_path / "ledger" / "runs"
    runs.mkdir(parents=True)
    for run_id, findings in (("found", [_finding()]), ("newer", [])):
        (runs / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "ai_findings": [asdict(item) for item in findings],
        }), encoding="utf-8")

    def fake_compile(finding, root, **kwargs):
        assert finding.id == "F1"
        assert root == tmp_path
        return smith.CompileResult("compiled", "F1", "R008", 1, None,
                                   tmp_path / "ledger" / "traces" / "mock.jsonl",
                                   after_ai_calls=0, after_seconds=0.0)

    monkeypatch.setattr(smith, "compile_finding", fake_compile)
    assert cli.run_compile("F1") == 0
    assert "Compiled R008" in capsys.readouterr().out
    assert cli.run_compile("F1", run_id="found") == 0
    assert cli.run_compile("F1", run_id="newer") == 2
    assert cli.main(["compile", "F1", "--run", "../found"]) == 2


def test_from_replays_offline_and_live_act3_baseline_is_cached(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    _project(tmp_path, monkeypatch)

    def fake_research(changes, rule_findings, **kwargs):
        assert rule_findings == ()
        assert kwargs["live"] in (True, False)
        return scholar.ScholarResult(
            findings=(_finding(),), ai_calls=4 if kwargs["live"] else 0,
            elapsed_seconds=0.0, trace_steps=(), ask_you=(),
            status="complete", run_id=kwargs["run_id"],
        )

    monkeypatch.setattr(scholar, "research_changes", fake_research)
    monkeypatch.setattr(smith, "compile_finding", lambda finding, root, **kwargs:
                        smith.CompileResult("compiled", finding.id, "R008", 1, None,
                                            root / "ledger" / "traces" / "mock.jsonl",
                                            after_ai_calls=0, after_seconds=0.0))
    assert cli.run_compile("F1", from_plan=ACT2) == 0
    assert "AI calls: 0" in capsys.readouterr().out

    assert cli.run_check(ACT3, scholar_mode="live", disabled_rules=("R007",)) == 0
    baseline = cli._baseline()
    assert baseline["ai_calls"] == 4
    assert (tmp_path / "ledger" / "runs" / f"{baseline['run_id']}.json").exists()

    demo_plan = tmp_path / "fixtures" / "plans" / ACT3.name
    demo_plan.parent.mkdir(parents=True)
    demo_plan.write_bytes(ACT3.read_bytes())
    assert cli.main(["demo", "act3"]) == 0
    assert ("AI advice (act2) -> learned, enforced rule (act3): "
            f"4 AI calls / {baseline['elapsed_seconds']:.2f} s "
            "-> 0 AI calls / 0.00 s") in capsys.readouterr().out


def test_live_cache_origin_is_saved_and_replay_is_linked(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    _project(tmp_path, monkeypatch)
    cache_path = tmp_path / ".cache" / "scholar" / "synthetic.json"

    def fake_research(changes, rule_findings, **kwargs):
        if kwargs["live"]:
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(json.dumps({"version": 1, "responses": []}), encoding="utf-8")
            return scholar.ScholarResult(
                findings=(), ai_calls=2, elapsed_seconds=0.0, trace_steps=(), ask_you=(),
                status="complete", run_id=kwargs["run_id"], cache_paths=(cache_path,),
            )
        origin = json.loads(cache_path.read_text(encoding="utf-8"))["origin"]
        return scholar.ScholarResult(
            findings=(), ai_calls=0, elapsed_seconds=0.0, trace_steps=(), ask_you=(),
            status="complete", run_id=kwargs["run_id"],
            replayed_from_run_id=origin["run_id"],
            original_ai_calls=origin["ai_calls"],
            original_elapsed_seconds=origin["elapsed_seconds"],
        )

    monkeypatch.setattr(scholar, "research_changes", fake_research)
    assert cli.run_check(ACT3, scholar_mode="live", disabled_rules=("R007",)) == 0
    live = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    origin = json.loads(cache_path.read_text(encoding="utf-8"))["origin"]
    assert origin == {"run_id": live["run_id"], "ai_calls": 2,
                      "elapsed_seconds": live["elapsed_seconds"]}

    capsys.readouterr()
    assert cli.run_check(ACT3, scholar_mode="offline", disabled_rules=("R007",)) == 0
    replay = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert replay["ai_calls"] == 0
    assert replay["replayed_from_run_id"] == live["run_id"]
    assert replay["original_ai_calls"] == 2
    assert replay["original_elapsed_seconds"] == live["elapsed_seconds"]
    assert "replayed (offline) - original live run: 2 AI calls" in capsys.readouterr().out
