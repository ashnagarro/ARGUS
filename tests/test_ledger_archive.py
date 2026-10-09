"""Archived history remains available while the latest console session stays clean."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from argus import cli
from argus.ledger import archive_ledger


def _save_run(root: Path, run_id: str, when: str, step: str) -> None:
    runs = root / "ledger" / "runs"
    traces = root / "ledger" / "traces"
    runs.mkdir(parents=True, exist_ok=True)
    traces.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "run_at": when, "plan": f"{run_id}.json",
        "verdict": "GO", "ai_calls": 0, "elapsed_seconds": 0.1,
    }), encoding="utf-8")
    (traces / f"{run_id}.jsonl").write_text(
        json.dumps({"event": "tool_result", "step": step}) + "\n", encoding="utf-8")
    with (root / "ledger" / "ledger.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"run_id": run_id, "verdict": "GO"}) + "\n")


def test_archive_preserves_history_and_console_scopes(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    _save_run(tmp_path, "old-run", "2026-10-01T00:00:00+00:00", "old trace")
    old_path = tmp_path / "ledger" / "runs" / "old-run.json"
    old_record = json.loads(old_path.read_text(encoding="utf-8"))
    old_record.update(ai_calls=3, elapsed_seconds=4.5)
    old_path.write_text(json.dumps(old_record), encoding="utf-8")

    assert cli.main(["ledger", "archive"]) == 0
    assert "Archive:" in capsys.readouterr().out
    archives = list((tmp_path / "ledger" / "archive").iterdir())
    assert len(archives) == 1
    archive = archives[0]
    assert (archive / "runs" / "old-run.json").is_file()
    assert (archive / "traces" / "old-run.jsonl").read_text(encoding="utf-8").count("old trace") == 1
    assert "old-run" in (archive / "ledger.jsonl").read_text(encoding="utf-8")
    assert not (tmp_path / "ledger" / "runs").exists()
    assert not (tmp_path / "ledger" / "traces").exists()
    assert not (tmp_path / "ledger" / "ledger.jsonl").exists()
    assert cli._saved_run("unused", "old-run")["run_id"] == "old-run"

    _save_run(tmp_path, "new-run", "2026-10-09T00:00:00+00:00", "new trace")
    new_path = tmp_path / "ledger" / "runs" / "new-run.json"
    new_record = json.loads(new_path.read_text(encoding="utf-8"))
    new_record.update(replayed_from_run_id="old-run", original_ai_calls=3,
                      original_elapsed_seconds=4.5)
    new_path.write_text(json.dumps(new_record), encoding="utf-8")
    assert cli.main(["console", "--session", "latest"]) == 0
    latest = (tmp_path / "reports" / "console.html").read_text(encoding="utf-8")
    assert ">new-run.json</button>" in latest and ">old-run.json</button>" not in latest
    assert "new trace" in latest and "old trace" not in latest
    assert "latest session" in latest
    assert archive.name in latest
    assert "replayed (offline) - original live run:" in latest
    assert "3 AI calls, 4.50 s" in latest
    assert f'href="../ledger/archive/{archive.name}/runs/old-run.json"' in latest

    assert cli.main(["console", "--all"]) == 0
    all_runs = (tmp_path / "reports" / "console.html").read_text(encoding="utf-8")
    assert "new-run.json" in all_runs and "old-run.json" in all_runs
    assert "new trace" in all_runs and "old trace" in all_runs
    assert "all sessions" in all_runs
    assert "<strong>2</strong><span>Runs</span>" in all_runs
    assert 'href="#run-1"' in all_runs


def test_archive_name_collision_keeps_both_sessions(tmp_path: Path) -> None:
    instant = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    _save_run(tmp_path, "first", "2026-10-09T11:00:00+00:00", "first trace")
    first = archive_ledger(tmp_path, now=instant)
    assert first is not None
    _save_run(tmp_path, "second", "2026-10-09T12:00:00+00:00", "second trace")
    second = archive_ledger(tmp_path, now=instant)
    assert second is not None and second != first
    assert (first / "runs" / "first.json").is_file()
    assert (second / "runs" / "second.json").is_file()
    assert archive_ledger(tmp_path, now=instant) is None


def test_console_footer_tracks_feature_flags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    (tmp_path / "argus.toml").write_text(
        "[flags]\ngovernance_pack = true\nteam_overlays = true\npolicy_compiler = false\n",
        encoding="utf-8",
    )
    assert cli.main(["console"]) == 0
    html = (tmp_path / "reports" / "console.html").read_text(encoding="utf-8")
    works = html.split("<strong>Works now:</strong>", 1)[1].split("<strong>Prototype / roadmap:</strong>", 1)[0]
    prototype = html.split("<strong>Prototype / roadmap:</strong>", 1)[1].split("<strong>Archives:</strong>", 1)[0]
    assert "governance rule pack" in works and "team overlays" in works
    assert "governance rule pack" not in prototype and "team overlays" not in prototype
    assert "policy from English" in prototype and "policy from English" not in works
