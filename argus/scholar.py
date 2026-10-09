"""Evidence-checked Scholar research with live Responses and offline replay."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from .agent_loop import _redact_keys, append_trace, is_model_unavailable, run_agent_loop
from .corpus import Document
from .models import AIFinding, Change, RuleFinding
from .permissions import load_policy
from .verify import verify_finding


DEFAULT_MODEL = "gpt-6.1-sol"


class ScholarModelUnavailable(RuntimeError):
    """The configured model could not be used by this account."""


@dataclass(frozen=True, slots=True)
class ScholarResult:
    findings: tuple[AIFinding, ...]
    ai_calls: int
    elapsed_seconds: float
    trace_steps: tuple[str, ...]
    ask_you: tuple[str, ...]
    status: str
    run_id: str


class _ReplayResponses:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self._records = iter(records)

    def create(self, **_: Any) -> SimpleNamespace:
        try:
            record = next(self._records)
        except StopIteration as error:
            raise ValueError("cached Scholar responses ended before the final answer") from error
        return SimpleNamespace(
            output=[SimpleNamespace(**item) for item in record["output"]],
            output_text=record["output_text"],
        )


class _ReplayClient:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.responses = _ReplayResponses(records)


def _cache_key(change: Change, documents: Mapping[str, Document], model: str, schema: dict[str, Any]) -> str:
    material = {
        "model": model,
        "change": asdict(change),
        "documents": {
            doc_id: sha256(doc.body.encode("utf-8")).hexdigest()
            for doc_id, doc in sorted(documents.items())
        },
        "schema": schema,
    }
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return sha256(encoded).hexdigest()


def _read_cache(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("responses"), list):
        raise ValueError("unsupported Scholar cache format")
    records = payload["responses"]
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("output"), list) or not isinstance(record.get("output_text"), str):
            raise ValueError("invalid Scholar cache response")
    return records


def _write_cache(path: Path, records: tuple[dict[str, Any], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps({"version": 1, "responses": records}, ensure_ascii=False, sort_keys=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(_redact_keys(serialized) + "\n", encoding="utf-8")
    temporary.replace(path)


def _live_client() -> Any:
    # The credential is read only from the environment and passed directly to the SDK.
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --live Scholar research.")
    from openai import OpenAI

    return OpenAI(api_key=api_key, timeout=90.0, max_retries=0)


def _as_findings(payload: dict[str, Any], change: Change, documents: Mapping[str, Document]) -> tuple[AIFinding, ...]:
    findings: list[AIFinding] = []
    for item in payload["findings"]:
        checked = verify_finding(item["evidence"], documents)
        verified = checked.verified and item["resource"] == change.address
        reason = "resource_mismatch" if item["resource"] != change.address else checked.reason
        findings.append(AIFinding(
            id=item["id"],
            resource=item["resource"],
            change_type=item["change_type"],
            claim=item["claim"],
            evidence=checked.evidence if verified else tuple(item["evidence"]),
            severity=item["severity"],
            recommended_action=item["recommended_action"],
            confidence=item["confidence"],
            verified=verified,
            verification_reason=reason,
        ))
    return tuple(findings)


def research_changes(
    changes: Sequence[Change],
    rule_findings: Sequence[RuleFinding],
    *,
    documents: Mapping[str, Document],
    model: str = DEFAULT_MODEL,
    live: bool = False,
    client: Any | None = None,
    run_id: str | None = None,
    cache_dir: Path = Path(".cache/scholar"),
    trace_dir: Path = Path("ledger/traces"),
    permissions_path: Path = Path("permissions.yaml"),
    schema_path: Path = Path("schemas/finding.schema.json"),
    approval_callback: Callable[[str, str], bool] | None = None,
) -> ScholarResult:
    """Research only changes not already caught by a deterministic rule.

    In offline mode, replay a response sequence cached for the exact change,
    model, schema and corpus content. A cache miss asks for human attention.
    """
    started = perf_counter()
    run_id = run_id or uuid4().hex
    if not run_id or any(not (char.isalnum() or char in "_-") for char in run_id):
        raise ValueError("run_id must contain only letters, digits, underscore or hyphen")
    trace_path = trace_dir / f"{run_id}.jsonl"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    policy = load_policy(permissions_path)
    caught = {finding.resource for finding in rule_findings}
    all_findings: list[AIFinding] = []
    steps: list[str] = []
    ask_you: list[str] = []
    ai_calls = 0
    status = "complete"
    append_trace(trace_path, {"event": "scholar_started", "mode": "live" if live else "offline"})

    for change in changes:
        if change.address in caught:
            append_trace(trace_path, {"event": "scholar_skipped", "resource": change.address, "reason": "deterministic_rule"})
            continue
        key = _cache_key(change, documents, model, schema)
        cache_path = cache_dir / f"{key}.json"
        if live:
            active_client = client if client is not None else _live_client()
        else:
            try:
                active_client = _ReplayClient(_read_cache(cache_path))
            except (OSError, ValueError, TypeError, KeyError):
                message = f"No usable offline Scholar response for {change.address}; run --live or review it."
                ask_you.append(message)
                status = "needs_human"
                append_trace(trace_path, {"event": "cache_miss", "resource": change.address})
                continue
            append_trace(trace_path, {"event": "cache_replay", "resource": change.address})
        try:
            result = run_agent_loop(
                change, documents, client=active_client, model=model, schema=schema,
                policy=policy, trace_path=trace_path, count_api_calls=live,
                approval_callback=approval_callback,
            )
        except Exception as error:
            if is_model_unavailable(error):
                raise ScholarModelUnavailable(
                    f"Scholar model {model!r} is unavailable. Change the "
                    "`model = ...` line under `[scholar]` in argus.toml."
                ) from None
            if not live and isinstance(error, (OSError, ValueError, TypeError, KeyError)):
                message = f"Offline Scholar replay failed for {change.address}; review it or rerun --live."
                ask_you.append(message)
                status = "needs_human"
                append_trace(trace_path, {"event": "cache_replay_failed", "resource": change.address})
                continue
            raise
        if live and result.status == "complete":
            _write_cache(cache_path, result.response_records)
        ai_calls += result.ai_calls
        steps.extend(result.trace_steps)
        ask_you.extend(result.ask_you)
        if result.status != "complete":
            status = "needs_human"
        elif result.payload is not None:
            all_findings.extend(_as_findings(result.payload, change, documents))

    return ScholarResult(
        findings=tuple(all_findings),
        ai_calls=ai_calls,
        elapsed_seconds=perf_counter() - started,
        trace_steps=tuple(steps),
        ask_you=tuple(ask_you),
        status=status,
        run_id=run_id,
    )
