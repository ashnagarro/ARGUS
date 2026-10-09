"""Probe Scholar's OpenAI request in small, read-only stages."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tomllib
from typing import Any, Callable, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from argus.agent_loop import (  # noqa: E402
    TOOLS,
    _INSTRUCTIONS,
    _api_error_details,
    _redact_sensitive_text,
)
from argus.scholar import DEFAULT_MODEL  # noqa: E402


def _configured_model(root: Path) -> str:
    config = tomllib.loads((root / "argus.toml").read_text(encoding="utf-8"))
    return config.get("scholar", {}).get("model", DEFAULT_MODEL)


def _schema(root: Path) -> dict[str, Any]:
    return json.loads((root / "schemas" / "finding.schema.json").read_text(encoding="utf-8"))


def _format_api_error(error: Exception) -> str:
    """Show the same redacted diagnostic fields used by Scholar's trace."""
    details = _api_error_details(error)
    parts = [str(details["error_type"])]
    if "status_code" in details:
        parts.append(f"HTTP {details['status_code']}")
    for field in ("message", "body"):
        if field in details:
            parts.append(f"{field}: {details[field]}")
    return " | ".join(parts)


def _probe(label: str, call: Callable[[], Any], output: TextIO) -> bool:
    print(label, file=output)
    try:
        response = call()
    except Exception as error:
        print(f"  FAILED: {_format_api_error(error)}", file=output)
        return False
    status = getattr(response, "status", None)
    suffix = f" (response status: {_redact_sensitive_text(status)})" if isinstance(status, str) else ""
    print(f"  OK{suffix}", file=output)
    return True


def check_openai(*, client: Any, root: Path = PROJECT_ROOT, output: TextIO = sys.stdout) -> int:
    """Return 0 only when every request shape is accepted by this account."""
    try:
        model = _configured_model(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Could not read local Scholar configuration: {type(error).__name__}", file=output)
        return 1
    if not isinstance(model, str) or not model.strip():
        print("Configured [scholar] model in argus.toml must be a nonempty string.", file=output)
        return 1
    try:
        schema = _schema(root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Could not read local finding schema: {type(error).__name__}", file=output)
        return 1

    print("1. List models available to this API key", file=output)
    try:
        available = sorted(item.id for item in client.models.list().data)
    except Exception as error:
        print(f"  FAILED: {_format_api_error(error)}", file=output)
        return 1
    for model_id in available:
        print(f"  {_redact_sensitive_text(model_id)}", file=output)
    print(f"  Configured model in argus.toml: {_redact_sensitive_text(model)}", file=output)
    if model not in available:
        print("  FAILED: configured model is absent from this key's model list.", file=output)
        print("  Choose a compatible listed model, then change [scholar] model in argus.toml.", file=output)
        return 1
    print("  OK: configured model is listed", file=output)

    basic_ok = _probe(
        "2. Trivial Responses API call",
        lambda: client.responses.create(model=model, input="Reply OK."),
        output,
    )

    text = {"format": {"type": "json_schema", "name": "argus_findings", "schema": schema, "strict": True}}
    schema_ok = _probe(
        "3. Responses call with only the finding schema",
        lambda: client.responses.create(model=model, input='Return {"findings": []}.', text=text),
        output,
    )

    tools_ok = _probe(
        "4. Responses call with only Scholar tool definitions",
        lambda: client.responses.create(model=model, input="Reply OK.", tools=TOOLS),
        output,
    )
    if not (basic_ok and schema_ok and tools_ok):
        print("5. Combined Scholar request shape: SKIPPED because an isolated probe failed.", file=output)
        return 1

    if not _probe(
        "5. Combined Scholar request shape",
        lambda: client.responses.create(
            model=model,
            input=[{"role": "user", "content": 'Return {"findings": []}.'}],
            instructions=_INSTRUCTIONS,
            tools=TOOLS,
            text=text,
            parallel_tool_calls=False,
            store=False,
            include=["reasoning.encrypted_content"],
            timeout=30.0,
        ),
        output,
    ):
        return 1
    print("All five probes succeeded. Retry the act2 live check.", file=output)
    return 0


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is missing from this process environment.", file=sys.stderr)
        return 1
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=30.0, max_retries=0)
    return check_openai(client=client)


if __name__ == "__main__":
    raise SystemExit(main())
