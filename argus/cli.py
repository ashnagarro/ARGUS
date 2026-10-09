"""ARGUS command-line interface."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from time import perf_counter
import tomllib
from uuid import uuid4

from .corpus import load_corpus, read_section, search_corpus
from .corpus_fetch import fetch_corpus
from .models import AIFinding, RuleFinding
from .parse_plan import parse_plan
from .permissions import decide_permission, load_policy
from .report import Report, render_terminal, write_reports
from .rules import load_rules, run_rules
from .verdict import decide_verdict, merge_conditions
from .verify import verify_quote
from .warden import apply_exceptions, check_agent_files, load_agents, load_exceptions


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _append_trace(run_id: str, event: dict) -> None:
    trace_path = PROJECT_ROOT / "ledger" / "traces" / f"{run_id}.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")


def _settings() -> dict:
    return tomllib.loads((PROJECT_ROOT / "argus.toml").read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level parser and commands available so far."""
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Review infrastructure changes with evidence.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Check an infrastructure plan.")
    check.add_argument("plan", type=Path, help="Path to a plan JSON file.")
    check.add_argument(
        "--report-dir", type=Path, default=Path("reports"),
        help="Directory for latest.md and latest.html (default: reports).",
    )
    ai_mode = check.add_mutually_exclusive_group()
    ai_mode.add_argument("--offline", action="store_true", help="Replay cached Scholar answers.")
    ai_mode.add_argument("--live", action="store_true", help="Call the OpenAI API for uncovered changes.")
    check.add_argument(
        "--disable-rule", action="append", default=[], metavar="ID",
        help="Skip a deterministic rule for this check (repeatable).",
    )
    check.add_argument("--author", default="human", help="Change author, such as agent:smith.")
    check.add_argument("--changed-files", nargs="+", default=[], metavar="PATH",
                       help="Project-relative files changed by an agent.")

    compile_command = commands.add_parser(
        "compile", help="Compile an approved finding into a rule."
    )
    compile_command.add_argument("finding_id", help="ID of a VERIFIED Scholar finding.")
    source = compile_command.add_mutually_exclusive_group()
    source.add_argument("--run", dest="run_id", help="Use this saved run ID.")
    source.add_argument("--from", dest="from_plan", type=Path,
                        help="Replay this plan offline, then compile its finding.")

    demo = commands.add_parser("demo", help="Run a demonstration scenario.")
    demo.add_argument(
        "scenario",
        nargs="?",
        choices=("all", "act1", "act2", "act3", "act5"),
        help="Scenario to run.",
    )
    demo_mode = demo.add_mutually_exclusive_group()
    demo_mode.add_argument("--offline", action="store_true", help="Replay cached Scholar answers (default).")
    demo_mode.add_argument("--live", action="store_true", help="Call Scholar for research scenarios.")

    corpus = commands.add_parser("corpus", help="Manage reference documents.")
    corpus_commands = corpus.add_subparsers(dest="corpus_command", required=True)
    fetch = corpus_commands.add_parser("fetch", help="Fetch public reference documents.")
    fetch.add_argument(
        "--sources", type=Path, default=Path("corpus/sources.yaml"),
        help="Source manifest (default: corpus/sources.yaml).",
    )
    fetch.add_argument(
        "--output-dir", type=Path, default=Path("corpus"),
        help="Output directory (default: corpus).",
    )

    tool = commands.add_parser("tool", help="Use read-only corpus tools.")
    tool.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    tool_commands = tool.add_subparsers(dest="tool_command", required=True)
    search = tool_commands.add_parser("search-corpus", help="Search document sections.")
    search.add_argument("query")
    section = tool_commands.add_parser("read-section", help="Read one numbered section.")
    section.add_argument("doc_id")
    section.add_argument("number", type=int)
    quote = tool_commands.add_parser("verify-quote", help="Check a quote against one document.")
    quote.add_argument("doc_id")
    quote.add_argument("quote")
    return parser


def run_tool(command: str, args: argparse.Namespace) -> int:
    """Run a corpus lookup without invoking a model or changing documents."""
    run_id = uuid4().hex
    decision = decide_permission(
        command.replace("-", "_"), "", is_write=False,
        policy=load_policy(PROJECT_ROOT / "permissions.yaml"),
    )
    _append_trace(run_id, {
        "event": "permission_decision", "tool": command,
        "decision": decision.decision, "reason": decision.reason,
    })
    if not decision.approved:
        print(f"Ask you: approval required for {command}")
        return 2
    documents = load_corpus(args.corpus_dir)
    if command == "search-corpus":
        matches = search_corpus(args.query, documents)
        for section in matches:
            print(f"{section.doc_id} #{section.number}: {section.heading}")
        _append_trace(run_id, {"event": "tool_result", "tool": command, "matches": len(matches)})
        return 0
    if command == "read-section":
        section = read_section(args.doc_id, args.number, documents)
        print(f"{section.doc_id} #{section.number}: {section.heading}\n\n{section.text}")
        _append_trace(run_id, {"event": "tool_result", "tool": command,
                               "doc_id": args.doc_id, "number": args.number})
        return 0
    result = verify_quote(args.doc_id, args.quote, documents)
    _append_trace(run_id, {"event": "tool_result", "tool": command,
                           "doc_id": args.doc_id, "verified": result.verified,
                           "reason": result.reason})
    if result.verified:
        print(f"VERIFIED {args.doc_id}")
        return 0
    print(f"UNVERIFIED {args.doc_id}: {result.reason}")
    return 1


def _approve_smith_write(action: str) -> bool:
    """Require an affirmative human answer before Smith writes a rule."""
    print(f"Approval required: {action}")
    try:
        answer = input("Approve this write? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _saved_run(finding_id: str, run_id: str | None) -> dict:
    """Find a durable run, preferring the newest run containing this finding."""
    runs_dir = PROJECT_ROOT / "ledger" / "runs"
    if run_id is not None:
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid run ID")
        path = runs_dir / f"{run_id}.json"
        if not path.is_file():
            raise ValueError(f"run {run_id} was not found in ledger/runs")
        return json.loads(path.read_text(encoding="utf-8"))
    if runs_dir.is_dir():
        for path in sorted(runs_dir.glob("*.json"),
                           key=lambda item: item.stat().st_mtime_ns, reverse=True):
            record = json.loads(path.read_text(encoding="utf-8"))
            if any(item.get("id") == finding_id for item in record.get("ai_findings", [])):
                return record
    # Existing installations may have a last_run.json from before durable runs.
    legacy = PROJECT_ROOT / ".cache" / "last_run.json"
    if legacy.is_file():
        record = json.loads(legacy.read_text(encoding="utf-8"))
        if any(item.get("id") == finding_id for item in record.get("ai_findings", [])):
            return record
    raise ValueError(f"finding {finding_id} was not found in saved runs")


def _baseline() -> dict:
    path = PROJECT_ROOT / ".cache" / "act3_baseline.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _comparison(baseline: dict) -> str:
    return (f"before: {baseline['ai_calls']} AI calls, "
            f"{baseline['elapsed_seconds']:.2f} s  ->  after: 0 AI calls, 0.00 s")


def run_compile(
    finding_id: str, *, run_id: str | None = None, from_plan: Path | None = None,
) -> int:
    """Compile a verified finding from durable history or an offline replay."""
    from .smith import compile_finding

    if from_plan is not None:
        run_id = uuid4().hex
        code = run_check(from_plan, scholar_mode="offline", run_id=run_id,
                         force_scholar=True)
        if code == 2:
            return 2
    record = _saved_run(finding_id, run_id)
    raw = next((item for item in record.get("ai_findings", [])
                if item.get("id") == finding_id), None)
    if raw is None:
        print(f"argus compile: finding {finding_id} is not in run {record.get('run_id', 'unknown')}.", file=sys.stderr)
        return 2
    if not raw.get("verified"):
        print(f"argus compile: finding {finding_id} is UNVERIFIED; review its evidence.", file=sys.stderr)
        return 2
    finding = AIFinding(
        id=raw["id"], resource=raw["resource"], claim=raw["claim"],
        severity=raw["severity"], recommended_action=raw["recommended_action"],
        verified=True, verification_reason=raw.get("verification_reason"),
        evidence=tuple(raw["evidence"]), change_type=raw.get("change_type", ""),
        confidence=raw.get("confidence", ""),
    )
    baseline = _baseline()
    smith_settings = _settings().get("smith", {})
    executable = smith_settings.get("codex_executable", "codex")
    result = compile_finding(
        finding, PROJECT_ROOT, approve=_approve_smith_write,
        codex_executable=executable,
        codex_home=smith_settings.get("codex_home"),
        before_ai_calls=baseline.get("ai_calls"),
        before_seconds=baseline.get("elapsed_seconds"),
    )
    if result.status != "compiled":
        print(f"Ask you: {result.reason or 'Smith needs human review.'}")
        print(f"Trace: {result.trace_path}")
        return 2
    print(f"Compiled {result.rule_id} from {finding_id} in {result.attempts} attempt(s).")
    if result.before_ai_calls is None or result.before_seconds is None:
        print("act3 before: not measured; run act3 with --live --disable-rule R007 to record a baseline.")
    else:
        print(_comparison(baseline))
    print(f"Trace: {result.trace_path}")
    return 0


def run_check(
    plan: Path, report_dir: Path = Path("reports"), *,
    scholar_mode: str | None = None,
    disabled_rules: Sequence[str] = (),
    run_id: str | None = None,
    force_scholar: bool = False,
    author: str = "human",
    changed_files: Sequence[str] = (),
) -> int:
    """Run rules and optionally research uncovered changes with Scholar."""
    if report_dir == Path("reports"):
        report_dir = PROJECT_ROOT / report_dir
    started = perf_counter()
    run_id = run_id or uuid4().hex
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run ID")
    unknown = set(disabled_rules) - {rule.id for rule in load_rules()}
    if unknown:
        raise ValueError(f"unknown rule ID: {', '.join(sorted(unknown))}")
    _append_trace(run_id, {"event": "run_start", "mode": scholar_mode or "rules",
                           "disabled_rules": list(disabled_rules)})
    changes = parse_plan(plan)
    if author.startswith("agent:") and not changed_files:
        raise ValueError("--changed-files is required for an agent author")
    if changed_files and not author.startswith("agent:"):
        raise ValueError("--changed-files requires --author agent:<name>")
    policy = load_policy(PROJECT_ROOT / "permissions.yaml")
    permission_asks: list[str] = []
    for change in changes:
        decision = decide_permission("get_change", change.resource_type,
                                     is_write=False, policy=policy)
        _append_trace(run_id, {"event": "permission_decision", "action": "get_change",
                               "resource": change.address, "decision": decision.decision,
                               "reason": decision.reason})
        if not decision.approved:
            permission_asks.append(f"Approval required to review {change.address}: {decision.reason}.")
    for file in changed_files:
        decision = decide_permission("agent_change", "", is_write=True, policy=policy)
        _append_trace(run_id, {"event": "permission_decision", "action": "agent_change",
                               "file": file, "decision": decision.decision,
                               "reason": decision.reason})
        permission_asks.append(f"Human approval required for agent change to {file}.")
    rule_findings = tuple(
        run_rules(changes, disabled_rule_ids=disabled_rules)
        if disabled_rules else run_rules(changes)
    )
    if author.startswith("agent:"):
        agents = load_agents(PROJECT_ROOT / "agents.yaml")
        rule_findings += check_agent_files(author, changed_files, agents)
    exceptions_path = PROJECT_ROOT / "exceptions.yaml"
    exceptions = load_exceptions(exceptions_path)
    rule_findings = apply_exceptions(
        rule_findings, exceptions,
        datetime.now(timezone(timedelta(hours=5, minutes=30))).date(),
    )
    _append_trace(run_id, {"event": "rules_result", "changes": len(changes),
                           "finding_ids": [item.rule_id for item in rule_findings]})
    ai_findings = ()
    ai_calls = 0
    trace_steps: tuple[str, ...] = (f"checked {len(changes)} changes against deterministic rules",)
    if author.startswith("agent:"):
        trace_steps += (f"checked {len(changed_files)} agent files against allowed scope",)
    ask_you: tuple[str, ...] = ()
    scholar_status = "not_run"
    if scholar_mode is not None:
        from .scholar import ScholarModelUnavailable, research_changes

        model = _settings().get("scholar", {}).get("model", "gpt-6.1-sol")
        if not isinstance(model, str) or not model.strip():
            raise ValueError('set [scholar] model = "gpt-6.1-sol" in argus.toml')
        try:
            result = research_changes(
                changes, () if force_scholar else rule_findings,
                documents=load_corpus(PROJECT_ROOT / "corpus"),
                model=model, live=scholar_mode == "live", run_id=run_id,
                cache_dir=PROJECT_ROOT / ".cache" / "scholar",
                trace_dir=PROJECT_ROOT / "ledger" / "traces",
                permissions_path=PROJECT_ROOT / "permissions.yaml",
                schema_path=PROJECT_ROOT / "schemas" / "finding.schema.json",
            )
        except Exception as error:
            scholar_status = "needs_human"
            error_type = type(error).__name__
            _append_trace(run_id, {"event": "scholar_failed", "error_type": error_type})
            if isinstance(error, ScholarModelUnavailable):
                ask_you = (str(error),)
            elif isinstance(error, RuntimeError) and str(error) == "OPENAI_API_KEY is required for --live Scholar research.":
                ask_you = ("OPENAI_API_KEY is required for --live Scholar research.",)
            else:
                ask_you = (f"Scholar stopped before completing the review ({error_type}); review this change.",)
        else:
            ai_findings = tuple(result.findings)
            ai_calls = result.ai_calls
            trace_steps += tuple(result.trace_steps)
            ask_you = tuple(result.ask_you)
            scholar_status = result.status
    # A partial Scholar review cannot authorize a merge, even when the
    # deterministic rules found no problem. Keep the final decision closed.
    scholar_incomplete = scholar_mode is not None and scholar_status != "complete"
    verdict = "NEEDS HUMAN" if scholar_incomplete else decide_verdict(rule_findings, ai_findings)
    if permission_asks and verdict in ("GO", "GO-WITH-CONDITIONS"):
        verdict = "NEEDS HUMAN"
    if scholar_incomplete and not ask_you:
        status_text = scholar_status.replace("_", " ")
        ask_you = (f"Scholar review did not complete ({status_text}); review this change.",)
    ask_you += tuple(permission_asks)
    report = Report(
        verdict=verdict,
        run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        elapsed_seconds=perf_counter() - started,
        ai_calls=ai_calls,
        rule_findings=rule_findings,
        ai_findings=ai_findings,
        conditions=merge_conditions(rule_findings, ai_findings),
        trace_steps=trace_steps,
        ask_you=ask_you,
        review_status=scholar_status,
    )
    write_reports(report, report_dir)
    latest = PROJECT_ROOT / ".cache" / "last_run.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    run_record = {
        "run_id": run_id, "plan": str(Path(plan).resolve()),
        "run_at": report.run_at,
        "verdict": verdict, "scholar_status": scholar_status,
        "ai_calls": ai_calls, "elapsed_seconds": report.elapsed_seconds,
        "disabled_rules": list(disabled_rules),
        "author": author, "changed_files": list(changed_files),
        "rule_findings": [asdict(finding) for finding in rule_findings],
        "ai_findings": [asdict(finding) for finding in ai_findings],
    }
    serialized = json.dumps(run_record, sort_keys=True, ensure_ascii=False)
    runs_dir = PROJECT_ROOT / "ledger" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    with (runs_dir / f"{run_id}.json").open("x", encoding="utf-8") as stream:
        stream.write(serialized + "\n")
    latest.write_text(serialized, encoding="utf-8")
    if (Path(plan).name == "act3_major_upgrade_second.json" and scholar_mode == "live"
            and "R007" in disabled_rules and scholar_status == "complete" and ai_calls > 0):
        (PROJECT_ROOT / ".cache" / "act3_baseline.json").write_text(json.dumps({
            "run_id": run_id, "ai_calls": ai_calls,
            "elapsed_seconds": report.elapsed_seconds,
        }, sort_keys=True), encoding="utf-8")
    _append_trace(run_id, {"event": "run_end", "verdict": verdict,
                           "scholar_status": scholar_status, "ai_calls": ai_calls})
    ledger_path = PROJECT_ROOT / "ledger" / "ledger.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "run_id": run_id, "time": report.run_at, "author": author,
            "input_hash": sha256(Path(plan).read_bytes()).hexdigest(),
            "verdict": verdict, "ai_calls": ai_calls,
            "finding_ids": [item.rule_id for item in rule_findings]
            + [item.id for item in ai_findings],
        }, sort_keys=True) + "\n")
    print(f"Run ID: {run_id}")
    print(render_terminal(report))
    if verdict == "NEEDS HUMAN":
        return 2
    if verdict == "NO-GO":
        return 1
    return 0


def run_demo(scenario: str = "all", *, live: bool = False) -> int:
    """Show the four planned scenarios with an offline replay by default."""
    scenarios = ("act1", "act2", "act3", "act5") if scenario == "all" else (scenario,)
    plans = PROJECT_ROOT / "fixtures" / "plans"
    for name in scenarios:
        print(f"\n=== {name.upper()} ===")
        if name == "act1":
            code = run_check(plans / "act1_replace_pii_db.json")
            if code != 1:
                print("Ask you: act1 did not produce the expected NO-GO verdict.")
                return 2
        elif name == "act2":
            code = run_check(
                plans / "act2_major_upgrade.json",
                scholar_mode="live" if live else "offline",
                disabled_rules=("R007",),
            )
            if code == 2:
                return 2
            record = json.loads((PROJECT_ROOT / ".cache" / "last_run.json").read_text(encoding="utf-8"))
            if not record["ai_findings"]:
                print("Ask you: act2 has no Scholar finding to demonstrate.")
                return 2
        elif name == "act3":
            plan = plans / "act3_major_upgrade_second.json"
            if live:
                before_code = run_check(plan, scholar_mode="live", disabled_rules=("R007",))
                if before_code == 2:
                    return 2
            baseline = _baseline()
            if not baseline:
                print("Ask you: record act3 with --live --disable-rule R007 first.")
                return 2
            code = run_check(plan)
            if code != 1:
                print("Ask you: act3 did not produce the expected R007 NO-GO verdict.")
                return 2
            record = json.loads((PROJECT_ROOT / ".cache" / "last_run.json").read_text(encoding="utf-8"))
            if not any(item["rule_id"] == "R007" for item in record["rule_findings"]):
                print("Ask you: R007 did not catch act3.")
                return 2
            print(_comparison(baseline))
        elif name == "act5":
            code = run_check(
                plans / "act5_agent_landing_zone.json", author="agent:landing-zone",
                changed_files=("argus/rules/r007.py",),
            )
            if code != 1:
                print("Ask you: Warden did not block the out-of-scope agent file.")
                return 2
            record = json.loads((PROJECT_ROOT / ".cache" / "last_run.json").read_text(encoding="utf-8"))
            warden = next((RuleFinding(**item) for item in record["rule_findings"]
                           if item["rule_id"] == "W001"), None)
            if warden is None:
                print("Ask you: Warden finding W001 is missing.")
                return 2
            today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
            exception = ({
                "rule_id": "W001", "resource": warden.resource,
                "owner": "synthetic-team", "reason": "demo approval",
                "ticket": "DEMO-1", "expires": (today + timedelta(days=1)).isoformat(),
            },)
            active = apply_exceptions((warden,), exception, today)[0]
            expired = apply_exceptions((warden,), exception, today + timedelta(days=2))[0]
            print(f"Active exception: {'WAIVED' if active.waived else 'NO-GO'} until {exception[0]['expires']}")
            print(f"Expired exception: {'NO-GO' if not expired.waived else 'WAIVED'} — {expired.message}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch an ARGUS command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            mode = "live" if args.live else "offline" if args.offline else None
            return run_check(args.plan, args.report_dir, scholar_mode=mode,
                             disabled_rules=args.disable_rule, author=args.author,
                             changed_files=args.changed_files)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"argus check: {error}", file=sys.stderr)
            return 2
    if args.command == "compile":
        try:
            return run_compile(args.finding_id, run_id=args.run_id,
                               from_plan=args.from_plan)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"argus compile: {error}", file=sys.stderr)
            return 2
    if args.command == "demo":
        try:
            return run_demo(args.scenario or "all", live=args.live)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"argus demo: {error}", file=sys.stderr)
            return 2
    if args.command == "corpus" and args.corpus_command == "fetch":
        try:
            results = fetch_corpus(args.sources, args.output_dir)
        except (OSError, ValueError) as error:
            print(f"argus corpus fetch: {error}", file=sys.stderr)
            return 2
        for result in results:
            if result.status == "ok":
                print(f"OK {result.doc_id}: {result.size} bytes -> {result.path}")
            else:
                print(f"FAILED {result.doc_id}: {result.error}", file=sys.stderr)
        return 0 if all(result.status == "ok" for result in results) else 1
    if args.command == "tool":
        try:
            return run_tool(args.tool_command, args)
        except (OSError, KeyError, ValueError) as error:
            print(f"argus tool: {error}", file=sys.stderr)
            return 2
    print(f"argus {args.command}: not implemented yet", file=sys.stderr)
    return 2
