"""Codex MCP tools for ledger-backed ARGUS reviews (stdio transport)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from . import cli
from .corpus import load_corpus
from .models import RuleFinding
from .report import finding_detail, finding_label
from .rules import load_rules, resolve_rule_id
from .warden import W001_APPLIES_TO, W001_ID, W001_NAME, W001_TITLE
from .verdict import verdict_explanation, verdict_label
from .upgrade import UpgradeSpec


PROJECT_ROOT = cli.PROJECT_ROOT
mcp = MCPServer("ARGUS", description="Evidence-backed infrastructure plan safety gate")
READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def _log_call(tool: str, *, run_id: str, status: str) -> None:
    """Record a tool invocation without user input or environment values."""
    path = PROJECT_ROOT / "ledger" / "ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "event": "mcp_call", "tool": tool, "run_id": run_id,
        "author": "agent:codex", "status": status,
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def _run_records() -> list[dict]:
    directory = PROJECT_ROOT / "ledger" / "runs"
    if not directory.is_dir():
        return []
    records = []
    for path in directory.glob("*.json"):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda record: record.get("run_at", ""), reverse=True)


def _display_finding(item: dict) -> dict:
    """Put the human-facing rule text before its audit fields in MCP results."""
    if "rule_id" not in item:
        return {"title": item.get("claim", "Scholar finding"),
                "detail": f"Resource: {item.get('resource', '')} · Trigger: {item.get('claim', '')}",
                "reference": f"({item.get('id', '')})", **item}
    rule = next((candidate for candidate in load_rules(include_governance=True)
                 if candidate.id == item["rule_id"]), None)
    current = dict(item)
    if not current.get("name"):
        if rule is not None:
            current.update(title=rule.title, name=rule.name, applies_to=rule.applies_to)
        elif current["rule_id"] == W001_ID:
            current.update(title=W001_TITLE, name=W001_NAME, applies_to=W001_APPLIES_TO)
    applies_to = current.get("applies_to") or ()
    if applies_to:
        source_tool, cloud = applies_to[0].split("/", 1)
        current["source_tool"] = current.get("source_tool") or source_tool
        current["cloud"] = current.get("cloud") or ("n/a" if current["rule_id"] == W001_ID else cloud)
    finding = RuleFinding(**current)
    return {"title": finding.title, "detail": finding_detail(finding),
            "reference": finding_label(finding),
            **{key: value for key, value in current.items() if key != "title"}}


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
def argus_check(plan_path: str, live: bool = False) -> dict:
    """Review a project-local Terraform plan and save the decision in the ledger."""
    run_id = uuid4().hex
    try:
        plan = Path(plan_path)
        if not plan.is_absolute():
            plan = PROJECT_ROOT / plan
        plan = plan.resolve()
        if not plan.is_relative_to(PROJECT_ROOT.resolve()):
            raise ValueError("plan_path must stay inside the ARGUS project")
        if not plan.is_file() or plan.suffix.lower() != ".json":
            raise ValueError("plan_path must name an existing JSON file")
        _log_call("argus_check", run_id=run_id, status="started")
        cli.run_check(plan, scholar_mode="live" if live else None, run_id=run_id,
                      author="agent:codex", changed_files=(),
                      write_artifacts=False, emit_output=False, check_agent_scope=False)
        record = json.loads((PROJECT_ROOT / "ledger" / "runs" / f"{run_id}.json").read_text(encoding="utf-8"))
        _log_call("argus_check", run_id=run_id, status="completed")
        return {
            "verdict": record["verdict"],
            "verdict_label": verdict_label(record["verdict"]),
            "verdict_explanation": verdict_explanation(record["verdict"]),
            "findings": [_display_finding(item) for item in
                         record["rule_findings"] + record["ai_findings"]],
            "conditions": record["conditions"],
            "run_id": run_id,
        }
    except Exception:
        _log_call("argus_check", run_id=run_id, status="failed")
        raise


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
def argus_upgrade_check(
    plan_path: str, provider: str, from_version: str, to_version: str, live: bool = False,
) -> dict:
    """Check a project-local Terraform plan against the provider upgrade guide."""
    run_id = uuid4().hex
    try:
        plan = Path(plan_path)
        if not plan.is_absolute():
            plan = PROJECT_ROOT / plan
        plan = plan.resolve()
        if not plan.is_relative_to(PROJECT_ROOT.resolve()):
            raise ValueError("plan_path must stay inside the ARGUS project")
        if not plan.is_file() or plan.suffix.lower() != ".json":
            raise ValueError("plan_path must name an existing JSON file")
        upgrade = UpgradeSpec(provider, from_version, to_version)
        _log_call("argus_upgrade_check", run_id=run_id, status="started")
        cli.run_check(plan, scholar_mode="live" if live else "offline", run_id=run_id,
                      author="agent:codex", changed_files=(), check_agent_scope=False,
                      governance_enabled=False, team_enabled=False, upgrade=upgrade,
                      write_artifacts=False, emit_output=False)
        record = json.loads((PROJECT_ROOT / "ledger" / "runs" / f"{run_id}.json").read_text(encoding="utf-8"))
        _log_call("argus_upgrade_check", run_id=run_id, status="completed")
        return {
            "verdict": record["verdict"],
            "verdict_label": verdict_label(record["verdict"]),
            "verdict_explanation": verdict_explanation(record["verdict"]),
            "upgrade": record["upgrade"],
            "findings": [_display_finding(item) for item in record["ai_findings"]],
            "conditions": record["conditions"],
            "run_id": run_id,
        }
    except Exception:
        _log_call("argus_upgrade_check", run_id=run_id, status="failed")
        raise


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
def argus_explain(finding_id: str) -> dict:
    """Explain a saved rule or Scholar finding by audit ID or readable name."""
    call_id = uuid4().hex
    try:
        selected = None
        rule_id = resolve_rule_id(finding_id)
        for record in _run_records():
            selected = next((item for item in record.get("rule_findings", [])
                             if item.get("rule_id") == (rule_id or finding_id)
                             or item.get("name") == finding_id), None)
            if selected is None:
                selected = next((item for item in record.get("ai_findings", [])
                                 if item.get("id") == finding_id), None)
            if selected is not None:
                break
        if selected is None:
            raise ValueError(f"finding {finding_id} was not found in ledger/runs")
        evidence = list(selected.get("evidence") or [])
        source_id = selected.get("source_finding_id")
        if not evidence and source_id:
            for record in _run_records():
                source = next((item for item in record.get("ai_findings", [])
                               if item.get("id") == source_id and item.get("verified")), None)
                if source:
                    evidence = list(source.get("evidence") or [])
                    break
        if not evidence:
            documents = load_corpus(PROJECT_ROOT / "corpus")
            for doc_id in selected.get("source_doc_ids", []):
                document = documents.get(doc_id)
                if document:
                    evidence.append({"doc_id": doc_id, "url": document.url,
                                     "retrieved_at": document.retrieved_at})
        display = _display_finding(selected)
        result = {
            "title": display["title"],
            "detail": display["detail"],
            "reference": display["reference"],
            "finding_id": selected.get("rule_id") or selected.get("id"),
            "name": display.get("name", ""),
            "applies_to": display.get("applies_to", ()),
            "why": selected.get("why_it_matters") or selected.get("claim") or selected.get("message", ""),
            "how_to_fix": selected.get("how_to_fix") or selected.get("recommended_action", ""),
            "evidence": evidence,
        }
        _log_call("argus_explain", run_id=call_id, status="completed")
        return result
    except Exception:
        _log_call("argus_explain", run_id=call_id, status="failed")
        raise


def main() -> None:
    """Run the official SDK's stdio transport; stdout belongs to MCP."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
