"""Smoke tests for the Phase 1 command-line entry point."""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("command", [None, "check", "compile", "demo"])
def test_help_works(command: str | None) -> None:
    args = [sys.executable, "-m", "argus"]
    if command is not None:
        args.append(command)
    args.append("--help")

    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    if command is None:
        for name in ("check", "compile", "demo"):
            assert name in result.stdout
    else:
        assert command in result.stdout
