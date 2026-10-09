"""ARGUS command-line interface."""

import argparse
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
import sys
from time import perf_counter

from .corpus_fetch import fetch_corpus
from .parse_plan import parse_plan
from .report import Report, render_terminal, write_reports
from .rules import run_rules
from .verdict import decide_verdict, merge_conditions


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

    compile_command = commands.add_parser(
        "compile", help="Compile an approved finding into a rule."
    )
    compile_command.add_argument("finding_id", nargs="?", help="Finding ID.")

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
    return parser


def run_check(plan: Path, report_dir: Path = Path("reports")) -> int:
    """Evaluate one plan and write the Phase 4 reports."""
    started = perf_counter()
    changes = parse_plan(plan)
    rule_findings = tuple(run_rules(changes))
    verdict = decide_verdict(rule_findings)
    report = Report(
        verdict=verdict,
        run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        elapsed_seconds=perf_counter() - started,
        ai_calls=0,
        rule_findings=rule_findings,
        ai_findings=(),
        conditions=merge_conditions(rule_findings),
    )
    write_reports(report, report_dir)
    print(render_terminal(report))
    return 1 if verdict == "NO-GO" else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch an ARGUS command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        try:
            return run_check(args.plan, args.report_dir)
        except (OSError, ValueError) as error:
            print(f"argus check: {error}", file=sys.stderr)
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
    print(f"argus {args.command}: not implemented yet", file=sys.stderr)
    return 2
