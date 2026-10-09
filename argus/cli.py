"""ARGUS command-line parser."""

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Create the top-level parser and Phase 1 command placeholders."""
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Review infrastructure changes with evidence.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="Check an infrastructure plan.")
    check.add_argument("plan", nargs="?", help="Path to a plan JSON file.")

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse a command and report that its implementation is a later phase."""
    parser = build_parser()
    args = parser.parse_args(argv)
    parser.exit(2, f"argus {args.command}: not implemented yet\n")
    return 2
