"""Smoke tests for the Phase 1 command-line entry point."""

from pathlib import Path
import subprocess
import sys

import pytest

from argus import cli


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("command", [None, "check", "compile", "demo", "console", "ledger", "ledger archive", "corpus", "corpus fetch", "tool", "tool search-corpus", "tool read-section", "tool verify-quote"])
def test_help_works(command: str | None) -> None:
    args = [sys.executable, "-m", "argus"]
    if command is not None:
        args.extend(command.split())
    args.append("--help")

    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    if command is None:
        for name in ("check", "compile", "demo", "console", "ledger", "corpus", "tool"):
            assert name in result.stdout
    else:
        assert command.split()[-1] in result.stdout


def test_read_only_corpus_tools_use_local_fixture(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    (tmp_path / "permissions.yaml").write_bytes((ROOT / "permissions.yaml").read_bytes())
    base = ["tool", "--corpus-dir", str(ROOT / "tests" / "fixtures" / "corpus")]

    assert cli.main([*base, "search-corpus", "database replacement"]) == 0
    assert "synthetic-alpha #" in capsys.readouterr().out

    assert cli.main([*base, "read-section", "synthetic-alpha", "2"]) == 0
    assert "Before replacing the fictional database" in capsys.readouterr().out

    assert cli.main([*base, "verify-quote", "synthetic-alpha",
                     "Before replacing the fictional database, copy its sample records to a separate test snapshot."]) == 0
    assert "VERIFIED synthetic-alpha" in capsys.readouterr().out
