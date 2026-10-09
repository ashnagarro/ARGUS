"""MCP tool tests use an isolated ledger and a mocked stdio transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

from argus import cli, mcp_server


ROOT = Path(__file__).resolve().parents[1]


def _isolated_project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(mcp_server, "PROJECT_ROOT", tmp_path)
    (tmp_path / "permissions.yaml").write_bytes((ROOT / "permissions.yaml").read_bytes())
    (tmp_path / "exceptions.yaml").write_bytes((ROOT / "exceptions.yaml").read_bytes())
    (tmp_path / "fixtures" / "plans").mkdir(parents=True)
    plan = tmp_path / "fixtures" / "plans" / "act1.json"
    plan.write_bytes((ROOT / "fixtures" / "plans" / "act1_replace_pii_db.json").read_bytes())
    return plan


def test_mcp_tool_schemas_and_mocked_transport(monkeypatch) -> None:
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {"argus_check", "argus_explain"} <= names
    check = next(tool for tool in tools if tool.name == "argus_check")
    assert set(check.input_schema["required"]) == {"plan_path"}
    assert check.input_schema["properties"]["live"]["type"] == "boolean"
    for tool in tools:
        assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
    called = []
    monkeypatch.setattr(mcp_server.mcp, "run", lambda *, transport: called.append(transport))
    mcp_server.main()
    assert called == ["stdio"]


def test_mcp_launcher_from_agent_demo() -> None:
    async def list_tools() -> set[str]:
        server = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "argus_mcp.py")],
            cwd=ROOT / "examples" / "agent-demo",
        )
        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
                return {tool.name for tool in response.tools}

    assert {"argus_check", "argus_explain"} <= asyncio.run(list_tools())


def test_mcp_check_resolves_plan_paths_from_agent_demo(tmp_path: Path, monkeypatch) -> None:
    plan = _isolated_project(tmp_path, monkeypatch)
    monkeypatch.chdir(ROOT / "examples" / "agent-demo")
    for path in ("fixtures/plans/act1.json", str(plan)):
        outcome = mcp_server.argus_check(path)
        assert outcome["verdict"] == "NO-GO"
        assert (tmp_path / "ledger" / "runs" / f"{outcome['run_id']}.json").is_file()


def test_mcp_check_and_explain_write_ledger_only(tmp_path: Path, monkeypatch) -> None:
    _isolated_project(tmp_path, monkeypatch)
    outcome = mcp_server.argus_check("fixtures/plans/act1.json")
    assert outcome["verdict"] == "NO-GO"
    assert outcome["run_id"]
    assert outcome["findings"]
    assert outcome["conditions"]
    run = json.loads((tmp_path / "ledger" / "runs" / f"{outcome['run_id']}.json").read_text(encoding="utf-8"))
    assert run["author"] == "agent:codex"
    assert (tmp_path / "ledger" / "traces" / f"{outcome['run_id']}.jsonl").exists()
    explanation = mcp_server.argus_explain("R001")
    assert explanation["finding_id"] == "R001"
    assert explanation["why"]
    assert explanation["how_to_fix"]
    log = (tmp_path / "ledger" / "ledger.jsonl").read_text(encoding="utf-8")
    assert '"author": "agent:codex"' in log
    assert '"tool": "argus_check"' in log
    assert '"tool": "argus_explain"' in log
    assert not (tmp_path / ".cache").exists()
    assert not (tmp_path / "reports").exists()


def test_mcp_reviewer_is_not_treated_as_sensitive_change_author(tmp_path: Path, monkeypatch) -> None:
    plan = _isolated_project(tmp_path, monkeypatch)
    (tmp_path / "argus.toml").write_text("[flags]\ngovernance_pack = true\n", encoding="utf-8")
    payload = json.loads(plan.read_text(encoding="utf-8"))
    resource = payload["resource_changes"][0]
    resource["address"] = "aws_iam_role.synthetic"
    resource["type"] = "aws_iam_role"
    resource["name"] = "synthetic"
    resource["change"]["actions"] = ["update"]
    resource["change"]["before"] = {"tags": {"env": "dev"}}
    resource["change"]["after"] = {"tags": {"env": "dev"}}
    plan.write_text(json.dumps(payload), encoding="utf-8")

    outcome = mcp_server.argus_check("fixtures/plans/act1.json")
    assert all(finding["rule_id"] != "G28" for finding in outcome["findings"])
    run = json.loads((tmp_path / "ledger" / "runs" / f"{outcome['run_id']}.json").read_text(encoding="utf-8"))
    assert run["author"] == "agent:codex"


def test_mcp_rejects_plan_outside_project_and_logs_failure(tmp_path: Path, monkeypatch) -> None:
    _isolated_project(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="inside the ARGUS project"):
        mcp_server.argus_check(str(ROOT / "fixtures" / "plans" / "act1_replace_pii_db.json"))
    assert '"status": "failed"' in (tmp_path / "ledger" / "ledger.jsonl").read_text(encoding="utf-8")
    assert not (tmp_path / "reports").exists()
