"""ARGUS command-line interface."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html import escape
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


def _counted(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"


def _append_trace(run_id: str, event: dict) -> None:
    trace_path = PROJECT_ROOT / "ledger" / "traces" / f"{run_id}.jsonl"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    with trace_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")


def _settings() -> dict:
    path = PROJECT_ROOT / "argus.toml"
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


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
    check.add_argument("--ticket", help="Change ticket for governance review.")
    check.add_argument("--approver", help="Human approver identity for governance review.")
    check.add_argument("--tf-file", action="append", type=Path, default=[], metavar="PATH",
                       help="Terraform source file to scan for literal secrets (repeatable).")

    compile_command = commands.add_parser(
        "compile", help="Compile an approved finding into a rule."
    )
    compile_command.add_argument("finding_id", help="ID of a VERIFIED Scholar finding.")
    source = compile_command.add_mutually_exclusive_group()
    source.add_argument("--run", dest="run_id", help="Use this saved run ID.")
    source.add_argument("--from", dest="from_plan", type=Path,
                        help="Replay this plan offline, then compile its finding.")

    policy_command = commands.add_parser(
        "policy", help="Compile a human-approved English policy into a rule."
    )
    policy_command.add_argument("sentence", help="One precise policy sentence.")

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
    demo.add_argument("--present", action="store_true",
                      help="Write an offline projector view to reports/presentation.html.")

    console = commands.add_parser("console", help="Build the offline ARGUS Console HTML page.")
    console.add_argument("--open", action="store_true", help="Open the generated page in a browser.")
    console_scope = console.add_mutually_exclusive_group()
    console_scope.add_argument("--session", choices=("latest",), default="latest",
                               help="Show runs since the last archive (default: latest).")
    console_scope.add_argument("--all", action="store_true",
                               help="Include runs from every archived session.")

    ledger = commands.add_parser("ledger", help="Manage local run history.")
    ledger_commands = ledger.add_subparsers(dest="ledger_command", required=True)
    ledger_commands.add_parser("archive", help="Archive current ledger, runs, and traces.")

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
        paths = [runs_dir / f"{run_id}.json"]
        archive_root = PROJECT_ROOT / "ledger" / "archive"
        if archive_root.is_dir():
            paths.extend(archive / "runs" / f"{run_id}.json"
                         for archive in sorted(archive_root.iterdir(), reverse=True)
                         if archive.is_dir() and not archive.is_symlink())
        for path in paths:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        raise ValueError(f"run {run_id} was not found in current or archived runs")
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
    return ("AI advice (act2) -> learned, enforced rule (act3): "
            f"{baseline['ai_calls']} AI calls / {baseline['elapsed_seconds']:.2f} s "
            "-> 0 AI calls / 0.00 s")


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


def run_policy(sentence: str) -> int:
    """Compile a user policy only when its optional feature is enabled."""
    from .policy import compile_policy

    settings = _settings()
    flags = settings.get("flags", {})
    if not isinstance(flags, dict) or flags.get("policy_compiler") is not True:
        print("argus policy: enable [flags] policy_compiler = true in argus.toml.",
              file=sys.stderr)
        return 2
    smith_settings = settings.get("smith", {})
    print(f"Policy: {sentence.strip()}")
    result = compile_policy(
        sentence, PROJECT_ROOT, approve=_approve_smith_write,
        codex_executable=smith_settings.get("codex_executable", "codex"),
        codex_home=smith_settings.get("codex_home"),
    )
    if result.status != "compiled":
        print(f"Ask you: {result.reason or 'Smith needs human review.'}")
        print(f"Trace: {result.trace_path}")
        return 2
    print(f"Compiled {result.rule_id} from human-supplied policy in {result.attempts} attempt(s).")
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
    ticket: str | None = None,
    approver: str | None = None,
    tf_files: Sequence[Path] = (),
    governance_enabled: bool | None = None,
    write_artifacts: bool = True,
    emit_output: bool = True,
    check_agent_scope: bool = True,
) -> int:
    """Run rules and optionally research uncovered changes with Scholar."""
    if report_dir == Path("reports"):
        report_dir = PROJECT_ROOT / report_dir
    started = perf_counter()
    run_id = run_id or uuid4().hex
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run ID")
    settings = _settings()
    flags = settings.get("flags", {})
    include_governance = (isinstance(flags, dict) and flags.get("governance_pack") is True
                          if governance_enabled is None else governance_enabled)
    unknown = set(disabled_rules) - {rule.id for rule in load_rules(include_governance=include_governance)}
    if unknown:
        raise ValueError(f"unknown rule ID: {', '.join(sorted(unknown))}")
    _append_trace(run_id, {"event": "run_start", "mode": scholar_mode or "rules",
                           "disabled_rules": list(disabled_rules)})
    changes = parse_plan(plan)
    if author.startswith("agent:") and not changed_files and check_agent_scope:
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
    if include_governance:
        from .governance import context_from_settings

        source_files = tuple(dict.fromkeys((*(Path(plan).parent.glob("*.tf")), *tf_files)))
        context = context_from_settings(
            settings, ticket=ticket,
            # A read-only MCP review is performed by an agent, but the plan's
            # change author is unknown. Do not treat the reviewer as its author.
            author=author if check_agent_scope else "unknown", approver=approver,
            tf_files=source_files, ledger_recorded=True,
        )
        rule_findings = tuple(run_rules(
            changes, disabled_rule_ids=disabled_rules, include_governance=True,
            governance_context=context, controls_path=PROJECT_ROOT / "controls.yaml",
        ))
    else:
        rule_findings = tuple(
            run_rules(changes, disabled_rule_ids=disabled_rules)
            if disabled_rules else run_rules(changes)
        )
    if author.startswith("agent:") and check_agent_scope:
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
    trace_steps: tuple[str, ...] = (
        f"checked {_counted(len(changes), 'change')} against deterministic rules",
    )
    if author.startswith("agent:") and check_agent_scope:
        trace_steps += (f"checked {_counted(len(changed_files), 'agent file')} against allowed scope",)
    ask_you: tuple[str, ...] = ()
    scholar_status = "not_run"
    replayed_from_run_id: str | None = None
    original_ai_calls: int | None = None
    original_elapsed_seconds: float | None = None
    cache_paths: tuple[Path, ...] = ()
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
                cache_live_responses=write_artifacts,
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
            replayed_from_run_id = getattr(result, "replayed_from_run_id", None)
            original_ai_calls = getattr(result, "original_ai_calls", None)
            original_elapsed_seconds = getattr(result, "original_elapsed_seconds", None)
            cache_paths = getattr(result, "cache_paths", ())
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
        replayed_from_run_id=replayed_from_run_id,
        original_ai_calls=original_ai_calls,
        original_elapsed_seconds=original_elapsed_seconds,
    )
    if write_artifacts:
        write_reports(report, report_dir)
    latest = PROJECT_ROOT / ".cache" / "last_run.json"
    run_record = {
        "run_id": run_id, "plan": str(Path(plan).resolve()),
        "run_at": report.run_at,
        "verdict": verdict, "scholar_status": scholar_status,
        "ai_calls": ai_calls, "elapsed_seconds": report.elapsed_seconds,
        "scholar_mode": scholar_mode,
        "replayed_from_run_id": replayed_from_run_id,
        "original_ai_calls": original_ai_calls,
        "original_elapsed_seconds": original_elapsed_seconds,
        "disabled_rules": list(disabled_rules),
        "author": author, "changed_files": list(changed_files),
        "ticket": ticket, "approver": approver,
        "rule_findings": [asdict(finding) for finding in rule_findings],
        "ai_findings": [asdict(finding) for finding in ai_findings],
        "conditions": list(report.conditions),
        "trace_steps": list(report.trace_steps),
        "ask_you": list(report.ask_you),
    }
    serialized = json.dumps(run_record, sort_keys=True, ensure_ascii=False)
    runs_dir = PROJECT_ROOT / "ledger" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    with (runs_dir / f"{run_id}.json").open("x", encoding="utf-8") as stream:
        stream.write(serialized + "\n")
    if write_artifacts and scholar_mode == "live" and scholar_status == "complete" and cache_paths:
        from .scholar import stamp_cache_origin

        stamp_cache_origin(cache_paths, run_id, ai_calls, report.elapsed_seconds)
    if write_artifacts:
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(serialized, encoding="utf-8")
    if (write_artifacts and Path(plan).name == "act3_major_upgrade_second.json" and scholar_mode == "live"
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
    if emit_output:
        print(f"Run ID: {run_id}")
        print(render_terminal(report))
    if verdict == "NEEDS HUMAN":
        return 2
    if verdict == "NO-GO":
        return 1
    return 0


def _presentation_html(cards: list[tuple[str, str, str]]) -> str:
    blocks = []
    for name, verdict, detail in cards:
        badge = {"NO-GO": "no-go", "GO-WITH-CONDITIONS": "conditions",
                 "GO": "go"}.get(verdict, "needs-human")
        blocks.append(
            f'<section><h2>{escape(name.upper())}</h2>'
            f'<p class="badge {badge}">{escape(verdict)}</p>'
            f'<p>{escape(detail)}</p></section>'
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>ARGUS presentation</title><style>'
        'body{font:26px/1.4 system-ui,sans-serif;background:#101820;color:#f7fafc;'
        'max-width:1400px;margin:0 auto;padding:2rem}'
        'h1{font-size:3.2rem}h2{font-size:2.4rem;margin:.1rem 0}'
        'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(500px,1fr));gap:1.2rem}'
        'section{background:#1e2c38;border:2px solid #6d8799;border-radius:1rem;padding:1.5rem}'
        '.badge{font-size:2rem;font-weight:800;padding:.4rem .8rem;border-radius:.4rem;display:inline-block}'
        '.no-go{background:#a11825}.conditions{background:#9a5a00}.go{background:#176833}'
        '.needs-human{background:#70479a}</style></head><body>'
        '<h1>ARGUS — evidence-backed Terraform safety gate</h1><main>'
        + ''.join(blocks) + '</main></body></html>\n'
    )


def run_demo(scenario: str = "all", *, live: bool = False, present: bool = False) -> int:
    """Show the four planned scenarios with an offline replay by default."""
    scenarios = ("act1", "act2", "act3", "act5") if scenario == "all" else (scenario,)
    plans = PROJECT_ROOT / "fixtures" / "plans"
    cards: list[tuple[str, str, str]] = []
    for name in scenarios:
        print(f"\n=== {name.upper()} ===")
        if name == "act1":
            code = run_check(plans / "act1_replace_pii_db.json", governance_enabled=False)
            if code != 1:
                print("Ask you: act1 did not produce the expected NO-GO verdict.")
                return 2
            cards.append((name, "NO-GO", "A stateful production database replacement is blocked by a deterministic rule."))
        elif name == "act2":
            code = run_check(
                plans / "act2_major_upgrade.json",
                scholar_mode="live" if live else "offline",
                disabled_rules=("R007",),
                governance_enabled=False,
            )
            if code == 2:
                return 2
            record = json.loads((PROJECT_ROOT / ".cache" / "last_run.json").read_text(encoding="utf-8"))
            if not record["ai_findings"]:
                print("Ask you: act2 has no Scholar finding to demonstrate.")
                return 2
            cards.append((name, record["verdict"],
                          "Scholar's evidence-backed finding is advisory until a human approves a tested rule."))
        elif name == "act3":
            plan = plans / "act3_major_upgrade_second.json"
            if live:
                before_code = run_check(plan, scholar_mode="live", disabled_rules=("R007",),
                                        governance_enabled=False)
                if before_code == 2:
                    return 2
            baseline = _baseline()
            if not baseline:
                print("Ask you: record act3 with --live --disable-rule R007 first.")
                return 2
            code = run_check(plan, governance_enabled=False)
            if code != 1:
                print("Ask you: act3 did not produce the expected R007 NO-GO verdict.")
                return 2
            record = json.loads((PROJECT_ROOT / ".cache" / "last_run.json").read_text(encoding="utf-8"))
            if not any(item["rule_id"] == "R007" for item in record["rule_findings"]):
                print("Ask you: R007 did not catch act3.")
                return 2
            print(_comparison(baseline))
            cards.append((name, record["verdict"], _comparison(baseline)))
        elif name == "act5":
            code = run_check(
                plans / "act5_agent_landing_zone.json", author="agent:landing-zone",
                changed_files=("argus/rules/r007.py",),
                governance_enabled=False,
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
            print("Warden blocked agent:landing-zone: argus/rules/r007.py is outside its "
                  "allowed infra/landing-zone/** scope.")
            simulated_date = date(2026, 10, 9)
            active_exception = ({
                "rule_id": "W001", "resource": warden.resource,
                "owner": "synthetic-team", "reason": "demo approval",
                "ticket": "DEMO-1", "expires": "2026-12-31",
            },)
            expired_exception = ({**active_exception[0], "expires": "2026-10-01"},)
            active = apply_exceptions((warden,), active_exception, simulated_date)[0]
            expired = apply_exceptions((warden,), expired_exception, simulated_date)[0]
            print(f"Exception simulation date: {simulated_date.isoformat()}")
            print(f"Active exception: {'WAIVED' if active.waived else 'NO-GO'} until {active_exception[0]['expires']}")
            print(f"Expired exception: {'NO-GO' if not expired.waived else 'WAIVED'} on {expired_exception[0]['expires']} - {expired.message}")
            cards.append((name, record["verdict"],
                          "Agent landing-zone changed argus/rules/r007.py outside its approved scope; "
                          "an expired exception blocks it again."))
    if present:
        path = PROJECT_ROOT / "reports" / "presentation.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_presentation_html(cards), encoding="utf-8")
        print(f"Presentation: {path}")
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
                             changed_files=args.changed_files, ticket=args.ticket,
                             approver=args.approver, tf_files=args.tf_file)
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
    if args.command == "policy":
        try:
            return run_policy(args.sentence)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"argus policy: {error}", file=sys.stderr)
            return 2
    if args.command == "demo":
        try:
            return run_demo(args.scenario or "all", live=args.live,
                            present=args.present)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"argus demo: {error}", file=sys.stderr)
            return 2
    if args.command == "console":
        try:
            from .console import write_console

            output = write_console(PROJECT_ROOT, include_archives=args.all)
            print(f"Console: {output}")
            if args.open:
                import webbrowser

                webbrowser.open(output.as_uri())
            return 0
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"argus console: {error}", file=sys.stderr)
            return 2
    if args.command == "ledger" and args.ledger_command == "archive":
        try:
            from .ledger import archive_ledger

            archived = archive_ledger(PROJECT_ROOT)
            print(f"Archive: {archived}" if archived else "Nothing to archive.")
            return 0
        except OSError as error:
            print(f"argus ledger archive: {error}", file=sys.stderr)
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
