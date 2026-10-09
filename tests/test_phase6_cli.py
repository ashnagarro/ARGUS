"""Scholar to verdict/report integration without an API request."""

from __future__ import annotations

import json
from pathlib import Path

from argus import cli, scholar
from argus.models import AIFinding


ROOT = Path(__file__).resolve().parents[1]


def _policy_files(root: Path) -> None:
    for name in ("permissions.yaml", "exceptions.yaml"):
        (root / name).write_bytes((ROOT / name).read_bytes())


def test_verified_scholar_finding_reaches_report_and_last_run(
    tmp_path: Path, monkeypatch,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "synthetic.md").write_bytes(
        (ROOT / "tests" / "fixtures" / "corpus" / "synthetic-alpha.md").read_bytes()
    )
    (tmp_path / "argus.toml").write_text(
        '[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    _policy_files(tmp_path)
    finding = AIFinding(
        id="AI-SYNTHETIC", resource="aws_db_instance.orders",
        change_type="update", claim="Synthetic sourced concern",
        severity="medium", recommended_action="Choose a compatible test group.",
        confidence="high", verified=True,
        evidence=({"doc_id": "synthetic-alpha", "quote":
                   "Before replacing the fictional database, copy its sample records to a separate test snapshot."},),
    )
    def fake_research(changes, rule_findings, **kwargs):
        assert kwargs["model"] == "gpt-6.1-sol"
        assert kwargs["live"] is True
        assert len(changes) == 2
        assert not rule_findings
        return scholar.ScholarResult(
            findings=(finding,), ai_calls=2, elapsed_seconds=0.25,
            trace_steps=("searched local corpus", "verified synthetic quote"),
            ask_you=(), status="complete", run_id=kwargs["run_id"],
        )
    monkeypatch.setattr(scholar, "research_changes", fake_research)
    monkeypatch.setattr(cli, "run_rules", lambda changes: [])

    report_dir = tmp_path / "reports"
    code = cli.run_check(
        ROOT / "fixtures" / "plans" / "act2_major_upgrade.json",
        report_dir, scholar_mode="live",
    )

    assert code == 0
    report = (report_dir / "latest.md").read_text(encoding="utf-8")
    assert "GO-WITH-CONDITIONS" in report
    assert "AI calls:** 2" in report
    assert "AI-SYNTHETIC" in report
    assert "Choose a compatible test group." in report
    assert "Step 2: searched local corpus" in report
    last = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert last["ai_findings"][0]["verified"] is True
    assert last["ai_calls"] == 2


def test_scholar_needs_human_is_not_a_successful_check(tmp_path: Path, monkeypatch, capsys) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "synthetic.md").write_bytes(
        (ROOT / "tests" / "fixtures" / "corpus" / "synthetic-alpha.md").read_bytes()
    )
    (tmp_path / "argus.toml").write_text('[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    _policy_files(tmp_path)
    monkeypatch.setattr(scholar, "research_changes", lambda *args, **kwargs: scholar.ScholarResult(
        findings=(), ai_calls=0, elapsed_seconds=0.0, trace_steps=(),
        ask_you=("No cached answer; review the change.",), status="needs_human",
        run_id=kwargs["run_id"],
    ))

    code = cli.run_check(
        ROOT / "fixtures" / "plans" / "act2_major_upgrade.json",
        tmp_path / "reports", scholar_mode="offline",
    )

    assert code == 2
    report = (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")
    assert "No cached answer; review the change." in report
    assert "**Verdict:** NEEDS HUMAN" in report
    assert "Provisional verdict" not in report
    assert "**Verdict:** GO" not in report
    assert "Verdict: NEEDS HUMAN" in capsys.readouterr().out
    assert "Verdict:</strong> NEEDS HUMAN" in (
        tmp_path / "reports" / "latest.html"
    ).read_text(encoding="utf-8")
    last = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert last["verdict"] == "NEEDS HUMAN"


def test_incomplete_scholar_without_reason_still_fails_closed(tmp_path: Path, monkeypatch) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (tmp_path / "argus.toml").write_text('[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    _policy_files(tmp_path)
    monkeypatch.setattr(scholar, "research_changes", lambda *args, **kwargs: scholar.ScholarResult(
        findings=(), ai_calls=1, elapsed_seconds=0.0, trace_steps=(),
        ask_you=(), status="needs_human", run_id=kwargs["run_id"],
    ))

    code = cli.run_check(
        ROOT / "fixtures" / "plans" / "act2_major_upgrade.json",
        tmp_path / "reports", scholar_mode="live",
    )

    assert code == 2
    report = (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")
    assert "**Verdict:** NEEDS HUMAN" in report
    assert "Scholar review did not complete (needs human)" in report


def test_scholar_exception_writes_needs_human_report(tmp_path: Path, monkeypatch) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (tmp_path / "argus.toml").write_text('[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    _policy_files(tmp_path)

    def failing_research(*args, **kwargs):
        raise scholar.ScholarModelUnavailable(
            "Scholar model is unavailable. Change the `model = ...` line under `[scholar]` in argus.toml."
        )

    monkeypatch.setattr(scholar, "research_changes", failing_research)

    code = cli.run_check(
        ROOT / "fixtures" / "plans" / "act2_major_upgrade.json",
        tmp_path / "reports", scholar_mode="live",
    )

    assert code == 2
    report = (tmp_path / "reports" / "latest.md").read_text(encoding="utf-8")
    assert "**Verdict:** NEEDS HUMAN" in report
    assert "argus.toml" in report
