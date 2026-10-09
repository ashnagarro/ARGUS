"""Phase 9 demo runs repeatably without an API or real project writes."""

from __future__ import annotations

import json
from pathlib import Path
import re

from argus import cli, scholar
from argus.models import AIFinding


ROOT = Path(__file__).resolve().parents[1]


def test_demo_all_has_stable_verdicts_and_cached_comparison(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    for name in ("agents.yaml", "permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    (tmp_path / "argus.toml").write_text(
        '[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8",
    )
    (tmp_path / "corpus").mkdir()
    plans = tmp_path / "fixtures" / "plans"
    plans.mkdir(parents=True)
    for name in (
        "act1_replace_pii_db.json", "act2_major_upgrade.json",
        "act3_major_upgrade_second.json", "act5_agent_landing_zone.json",
    ):
        (plans / name).write_bytes((ROOT / "fixtures" / "plans" / name).read_bytes())
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "act3_baseline.json").write_text(
        json.dumps({"ai_calls": 13, "elapsed_seconds": 42.51}), encoding="utf-8",
    )

    def fake_research(changes, rule_findings, **kwargs):
        assert kwargs["live"] is False
        return scholar.ScholarResult(
            findings=(AIFinding(
                id="F1", resource="aws_db_instance.orders",
                claim="Synthetic major upgrade concern", severity="high",
                recommended_action="Choose a matching group.", verified=True,
            ),),
            ai_calls=0, elapsed_seconds=0.0, trace_steps=(), ask_you=(),
            status="complete", run_id=kwargs["run_id"],
        )

    monkeypatch.setattr(scholar, "research_changes", fake_research)
    expected = ["NO-GO", "GO-WITH-CONDITIONS", "NO-GO", "NO-GO"]
    for _ in range(3):
        assert cli.main(["demo", "all"]) == 0
        output = capsys.readouterr().out
        assert re.findall(r"^Verdict: (.+)$", output, re.MULTILINE) == expected
        assert all(f"=== ACT{number} ===" in output for number in (1, 2, 3, 5))
        assert ("AI advice (act2) -> learned, enforced rule (act3): "
                "13 AI calls / 42.51 s -> 0 AI calls / 0.00 s") in output
        assert "Warden blocked agent:landing-zone: argus/rules/r007.py is outside" in output
        assert "Step 1: checked 1 change against deterministic rules" in output
        assert "Step 2: checked 1 agent file against allowed scope" in output
        assert "Exception simulation date: 2026-10-09" in output
        assert "Active exception: WAIVED until 2026-12-31" in output
        assert "Expired exception: NO-GO on 2026-10-01" in output

    assert cli.main(["demo", "--present"]) == 0
    presentation = (tmp_path / "reports" / "presentation.html").read_text(encoding="utf-8")
    assert presentation.count("<section>") == 4
    assert "13 AI calls / 42.51 s -&gt; 0 AI calls / 0.00 s" in presentation
    assert "Agent landing-zone changed argus/rules/r007.py outside its approved scope" in presentation
    assert "<style>" in presentation and "<script src=" not in presentation
