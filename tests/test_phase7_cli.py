"""Phase 7 command wiring with a mocked Smith compiler."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from argus import cli, smith
from argus.models import AIFinding


def _finding(*, verified: bool = True) -> AIFinding:
    return AIFinding(
        id="AI-SYNTHETIC", resource="aws_db_instance.orders",
        change_type="update", claim="Synthetic parameter group concern",
        severity="medium", recommended_action="Choose a synthetic compatible group.",
        confidence="high", verified=verified,
        evidence=({"doc_id": "synthetic-alpha", "quote":
                   "Before replacing the fictional database, copy its sample records to a separate test snapshot."},),
    )


def _latest(root: Path, finding: AIFinding) -> None:
    cache = root / ".cache"
    cache.mkdir()
    (cache / "last_run.json").write_text(
        json.dumps({"ai_findings": [asdict(finding)]}), encoding="utf-8",
    )
    (root / "argus.toml").write_text(
        '[smith]\ncodex_executable = "custom-codex"\n'
        'codex_home = ".codex-home"\n', encoding="utf-8",
    )


def test_compile_uses_last_verified_finding_config_and_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    _latest(tmp_path, _finding())
    (tmp_path / ".cache" / "act3_baseline.json").write_text(
        json.dumps({"ai_calls": 3, "elapsed_seconds": 4.5}), encoding="utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    def fake_compile(finding, project_root, **kwargs):
        assert finding.id == "AI-SYNTHETIC"
        assert finding.verified is True
        assert project_root == tmp_path
        assert kwargs["codex_executable"] == "custom-codex"
        assert kwargs["codex_home"] == ".codex-home"
        assert kwargs["approve"]("synthetic rule write") is True
        assert kwargs["before_ai_calls"] == 3
        assert kwargs["before_seconds"] == 4.5
        return smith.CompileResult(
            status="compiled", finding_id=finding.id, rule_id="R007",
            attempts=2, reason=None, trace_path=tmp_path / "ledger" / "traces" / "test.jsonl",
            before_ai_calls=3, before_seconds=4.5,
            after_ai_calls=0, after_seconds=0.25,
        )

    monkeypatch.setattr(smith, "compile_finding", fake_compile)
    assert cli.run_compile("AI-SYNTHETIC") == 0
    output = capsys.readouterr().out
    assert "Compiled R007" in output
    assert "before: 3 AI calls, 4.50 s  ->  after: 0 AI calls, 0.00 s" in output


def test_compile_rejects_unverified_last_finding_before_smith(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    _latest(tmp_path, _finding(verified=False))
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(smith, "compile_finding", lambda *args, **kwargs: pytest.fail(
        "UNVERIFIED finding reached Smith"
    ))

    assert cli.run_compile("AI-SYNTHETIC") == 2
    assert "UNVERIFIED" in capsys.readouterr().err


def test_read_only_smith_reason_appears_in_ask_you(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    _latest(tmp_path, _finding())
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    reason = "codex ran read-only (project not trusted or sandbox restricted)"
    monkeypatch.setattr(smith, "compile_finding", lambda finding, root, **kwargs:
                        smith.CompileResult(
                            status="needs human", finding_id=finding.id, rule_id="R007",
                            attempts=1, reason=reason,
                            trace_path=root / "ledger" / "traces" / "test.jsonl",
                        ))

    assert cli.run_compile("AI-SYNTHETIC") == 2
    assert f"Ask you: {reason}" in capsys.readouterr().out
