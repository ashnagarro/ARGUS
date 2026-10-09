"""ARGUS command-line interface."""

import argparse
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter
import tomllib
from uuid import uuid4

from .corpus import load_corpus, read_section, search_corpus
from .corpus_fetch import fetch_corpus
from .models import AIFinding
from .parse_plan import parse_plan
from .permissions import decide_permission, load_policy
from .report import Report, render_terminal, write_reports
from .rules import run_rules
from .verdict import decide_verdict, merge_conditions
from .verify import verify_quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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

    compile_command = commands.add_parser(
        "compile", help="Compile an approved finding into a rule."
    )
    compile_command.add_argument("finding_id", help="ID of a VERIFIED finding from the last check.")

    demo = commands.add_parser("demo", help="Run a demonstration scenario.")
    demo.add_argument(
        "scenario",
        nargs="?",
        choices=("all", "act1", "act2", "act3", "act5"),
        help="Scenario to run.",
    )

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


def run_compile(finding_id: str) -> int:
    """Compile one verified finding from the immediately preceding check."""
    from .smith import compile_finding

    latest_path = PROJECT_ROOT / ".cache" / "last_run.json"
    if not latest_path.is_file():
        print("argus compile: no previous check was found; run argus check --live first.", file=sys.stderr)
        return 2
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    raw = next((item for item in latest.get("ai_findings", [])
                if item.get("id") == finding_id), None)
    if raw is None:
        print(f"argus compile: finding {finding_id} is not in the last check.", file=sys.stderr)
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
    baseline_path = PROJECT_ROOT / ".cache" / "act3_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.is_file() else {}
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
        print("act3 before: not measured; run act3 with --live before compiling to record a baseline.")
    else:
        print(f"act3 before: {result.before_ai_calls} AI calls, {result.before_seconds:.2f} seconds")
    print(f"act3 after: {result.after_ai_calls} AI calls, {result.after_seconds:.2f} seconds")
    print(f"Trace: {result.trace_path}")
    return 0


def run_check(
    plan: Path, report_dir: Path = Path("reports"), *,
    scholar_mode: str | None = None,
) -> int:
    """Run rules and optionally research uncovered changes with Scholar."""
    started = perf_counter()
    run_id = uuid4().hex
    _append_trace(run_id, {"event": "run_start", "mode": scholar_mode or "rules"})
    changes = parse_plan(plan)
    rule_findings = tuple(run_rules(changes))
    _append_trace(run_id, {"event": "rules_result", "changes": len(changes),
                           "finding_ids": [item.rule_id for item in rule_findings]})
    ai_findings = ()
    ai_calls = 0
    trace_steps: tuple[str, ...] = (f"checked {len(changes)} changes against deterministic rules",)
    ask_you: tuple[str, ...] = ()
    scholar_status = "not_run"
    if scholar_mode is not None:
        from .scholar import ScholarModelUnavailable, research_changes

        model = _settings().get("scholar", {}).get("model", "gpt-6.1-sol")
        if not isinstance(model, str) or not model.strip():
            raise ValueError('set [scholar] model = "gpt-6.1-sol" in argus.toml')
        try:
            result = research_changes(
                changes, rule_findings,
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
    if scholar_incomplete and not ask_you:
        status_text = scholar_status.replace("_", " ")
        ask_you = (f"Scholar review did not complete ({status_text}); review this change.",)
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
    latest.write_text(json.dumps({
        "run_id": run_id, "plan": str(Path(plan).resolve()),
        "verdict": verdict, "scholar_status": scholar_status,
        "ai_calls": ai_calls, "elapsed_seconds": report.elapsed_seconds,
        "ai_findings": [asdict(finding) for finding in ai_findings],
    }, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    if (Path(plan).name == "act3_major_upgrade_second.json" and scholar_mode == "live"
            and scholar_status == "complete" and ai_calls > 0):
        (PROJECT_ROOT / ".cache" / "act3_baseline.json").write_text(json.dumps({
            "run_id": run_id, "ai_calls": ai_calls,
            "elapsed_seconds": report.elapsed_seconds,
        }, sort_keys=True), encoding="utf-8")
    _append_trace(run_id, {"event": "run_end", "verdict": verdict,
                           "scholar_status": scholar_status, "ai_calls": ai_calls})
    print(render_terminal(report))
    if verdict == "NEEDS HUMAN":
        return 2
    if verdict == "NO-GO":
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch an ARGUS command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            mode = "live" if args.live else "offline" if args.offline else None
            return run_check(args.plan, args.report_dir, scholar_mode=mode)
        except (OSError, ValueError, RuntimeError) as error:
            print(f"argus check: {error}", file=sys.stderr)
            return 2
    if args.command == "compile":
        try:
            return run_compile(args.finding_id)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"argus compile: {error}", file=sys.stderr)
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
