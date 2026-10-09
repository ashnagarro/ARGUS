"""Smoke tests for the Phase 1 command-line entry point."""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("command", [None, "check", "compile", "demo", "corpus", "corpus fetch", "tool", "tool search-corpus", "tool read-section", "tool verify-quote"])
def test_help_works(command: str | None) -> None:
    args = [sys.executable, "-m", "argus"]
    if command is not None:
        args.extend(command.split())
    args.append("--help")

    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    if command is None:
        for name in ("check", "compile", "demo", "corpus", "tool"):
            assert name in result.stdout
    else:
        assert command.split()[-1] in result.stdout


def test_read_only_corpus_tools_use_local_fixture() -> None:
    base = [
        sys.executable, "-m", "argus", "tool", "--corpus-dir",
        str(ROOT / "tests" / "fixtures" / "corpus"),
    ]
    search = subprocess.run(
        [*base, "search-corpus", "database replacement"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert search.returncode == 0, search.stderr
    assert "synthetic-alpha #" in search.stdout

    section = subprocess.run(
        [*base, "read-section", "synthetic-alpha", "2"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert section.returncode == 0, section.stderr
    assert "Before replacing the fictional database" in section.stdout

    quote = subprocess.run(
        [*base, "verify-quote", "synthetic-alpha",
         "Before replacing the fictional database, copy its sample records to a separate test snapshot."],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert quote.returncode == 0, quote.stderr
    assert "VERIFIED synthetic-alpha" in quote.stdout
