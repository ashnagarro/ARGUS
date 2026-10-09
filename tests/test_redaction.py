"""Sensitive plan values never leave the Terraform adapter unredacted."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from argus import cli, mcp_server
from argus.console import write_console
from argus.parse_plan import parse_plan
from argus.redaction import REDACTED, redact_value


ROOT = Path(__file__).resolve().parents[1]
RISKY = ROOT / "fixtures" / "plans" / "real_risky_plan.json"
FAKE_PASSWORD = "Sup3rSecret-FAKE-123"


def test_recursive_sensitive_masks_and_credential_names() -> None:
    source = {
        "nested": [{"ordinary": "visible", "token": "fake-token"}],
        "password": "fake-password",
        "enable_key_rotation": True,
        "key_id": "fake-key-id",
    }
    masked = redact_value(source, {"nested": [{"ordinary": True}]})
    assert masked == {
        "nested": [{"ordinary": REDACTED, "token": REDACTED}],
        "password": REDACTED,
        "enable_key_rotation": True,
        "key_id": REDACTED,
    }
    assert source["password"] == "fake-password"
    assert redact_value({"values": ["a", "b"]}, {"values": [False, True]}) == {
        "values": ["a", REDACTED],
    }


def test_real_plan_password_absent_from_all_generated_surfaces(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    assert FAKE_PASSWORD in RISKY.read_text(encoding="utf-8")
    plan_dir = tmp_path / "fixtures" / "plans"
    plan_dir.mkdir(parents=True)
    plan = plan_dir / RISKY.name
    plan.write_bytes(RISKY.read_bytes())
    for name in ("permissions.yaml", "exceptions.yaml", "controls.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    (tmp_path / "argus.toml").write_text(
        "[flags]\ngovernance_pack = true\nteam_overlays = false\n", encoding="utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)

    changes = parse_plan(plan)
    serialized_changes = json.dumps([asdict(change) for change in changes])
    assert FAKE_PASSWORD not in serialized_changes
    assert REDACTED in serialized_changes

    cli.run_check(plan)
    terminal = capsys.readouterr().out
    mcp_result = mcp_server.argus_check(str(plan))
    write_console(tmp_path)
    assert FAKE_PASSWORD not in terminal
    assert FAKE_PASSWORD not in json.dumps(mcp_result)
    for folder in ("reports", "ledger", ".cache"):
        directory = tmp_path / folder
        if directory.exists():
            for output in directory.rglob("*"):
                if output.is_file():
                    assert FAKE_PASSWORD not in output.read_text(encoding="utf-8"), output
