"""Scholar tests replay recorded model decisions; no test calls an API."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from argus.agent_loop import _redact_keys, run_agent_loop
from argus.corpus import load_corpus
from argus.models import Change, RuleFinding
from argus.permissions import decide_permission, load_policy
from argus.scholar import ScholarModelUnavailable, _write_cache, research_changes


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "corpus"
SCHEMA = ROOT / "schemas" / "finding.schema.json"
POLICY = ROOT / "permissions.yaml"


class RecordedResponses:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = iter(records)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append({**kwargs, "input": list(kwargs["input"])})
        record = next(self.records)
        return SimpleNamespace(
            output=[SimpleNamespace(**item) for item in record["output"]],
            output_text=record["output_text"],
        )


class RecordedClient:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.responses = RecordedResponses(records)


def _records() -> list[dict[str, object]]:
    return json.loads((FIXTURES / "scholar_synthetic.json").read_text(encoding="utf-8"))["responses"]


def _change(resource_type: str = "aws_db_instance") -> Change:
    return Change(
        address="aws_db_instance.synthetic",
        resource_type=resource_type,
        canonical_type="database_instance",
        actions=("delete", "create"),
        before={"engine_version": "15.00"},
        after={"engine_version": "16.00"},
        replace_paths=(),
        tags={"env": "synthetic"},
        is_replace=False,
    )


def test_schema_rejects_extra_fields_at_every_level() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    answer = json.loads(_records()[-1]["output_text"])
    jsonschema.validate(answer, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**answer, "url": "https://untrusted.invalid"}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"findings": [{**answer["findings"][0], "url": "https://untrusted.invalid"}]}, schema)
    altered = json.loads(json.dumps(answer))
    altered["findings"][0]["evidence"][0]["url"] = "https://untrusted.invalid"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(altered, schema)


def test_recorded_tool_loop_verifies_finding_and_replays_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_key = "synthetic-openai-key-never-to-be-stored"
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)
    documents = load_corpus(FIXTURES)
    client = RecordedClient(_records())
    kwargs = {
        "documents": documents,
        "run_id": "synthetic-live",
        "cache_dir": tmp_path / "cache",
        "trace_dir": tmp_path / "traces",
        "permissions_path": POLICY,
        "schema_path": SCHEMA,
    }

    result = research_changes([_change()], [], live=True, client=client, **kwargs)

    assert result.status == "complete"
    assert result.ai_calls == 4
    assert result.findings[0].verified
    assert result.findings[0].evidence[0]["url"] == documents["synthetic-alpha"].url
    assert result.findings[0].evidence[0]["retrieved_at"] == documents["synthetic-alpha"].retrieved_at
    assert len(result.trace_steps) == 3
    assert client.responses.calls[0]["model"] == "gpt-6.1-sol"
    assert client.responses.calls[0]["text"]["format"]["type"] == "json_schema"
    assert client.responses.calls[0]["store"] is False
    assert client.responses.calls[1]["input"][-1]["type"] == "function_call_output"
    trace = (tmp_path / "traces" / "synthetic-live.jsonl").read_text(encoding="utf-8")
    assert trace.count('"event": "permission_decision"') == 3
    assert fake_key not in trace
    cache_file = next((tmp_path / "cache").glob("*.json"))
    assert fake_key not in cache_file.read_text(encoding="utf-8")

    offline = research_changes([_change()], [], live=False, **{**kwargs, "run_id": "synthetic-offline"})
    assert offline.status == "complete"
    assert offline.ai_calls == 0
    assert offline.findings == result.findings
    assert offline.trace_steps == result.trace_steps


def test_rule_caught_change_skips_scholar(tmp_path: Path) -> None:
    client = RecordedClient(_records())
    rule = RuleFinding("R001", _change().address, "Synthetic rule", "critical", "Caught")
    result = research_changes(
        [_change()], [rule], documents=load_corpus(FIXTURES), live=True, client=client,
        trace_dir=tmp_path / "traces", cache_dir=tmp_path / "cache",
        permissions_path=POLICY, schema_path=SCHEMA,
    )
    assert result.ai_calls == 0
    assert result.findings == ()
    assert len(client.responses.calls) == 0


def test_sensitive_change_requires_human_before_tool_runs(tmp_path: Path) -> None:
    client = RecordedClient(_records()[:1])
    result = run_agent_loop(
        _change("aws_iam_user"), load_corpus(FIXTURES), client=client, model="test-model",
        schema=json.loads(SCHEMA.read_text(encoding="utf-8")), policy=load_policy(POLICY),
        trace_path=tmp_path / "sensitive.jsonl",
    )
    assert result.status == "needs_human"
    assert result.tool_calls == 0
    assert "Human approval required" in result.ask_you[0]
    trace = (tmp_path / "sensitive.jsonl").read_text(encoding="utf-8")
    assert '"decision": "requires_human_approval"' in trace
    assert '"event": "tool_result"' not in trace


def test_tool_budget_stops_after_eight_calls(tmp_path: Path) -> None:
    call = {"output": [{"type": "function_call", "name": "get_change", "arguments": "{}", "call_id": "same"}], "output_text": ""}
    client = RecordedClient([call] * 8)
    result = run_agent_loop(
        _change(), load_corpus(FIXTURES), client=client, model="test-model",
        schema=json.loads(SCHEMA.read_text(encoding="utf-8")), policy=load_policy(POLICY),
        trace_path=tmp_path / "budget.jsonl",
    )
    assert result.status == "needs_human"
    assert result.tool_calls == 8
    assert result.ai_calls == 8
    assert "8 tool calls" in result.ask_you[0]
    assert len(client.responses.calls) == 8


def test_time_budget_and_invalid_answer_need_human(tmp_path: Path) -> None:
    now = iter([0.0, 91.0, 91.0])
    clock = lambda: next(now)
    client = RecordedClient([])
    common = dict(
        change=_change(), documents=load_corpus(FIXTURES), model="test-model",
        schema=json.loads(SCHEMA.read_text(encoding="utf-8")), policy=load_policy(POLICY),
    )
    timed = run_agent_loop(**common, client=client, trace_path=tmp_path / "timed.jsonl", clock=clock)
    assert timed.status == "needs_human"
    assert timed.ai_calls == 0
    assert "90-second" in timed.ask_you[0]

    invalid = RecordedClient([{"output": [], "output_text": '{"findings": [], "extra": 1}'}])
    result = run_agent_loop(**common, client=invalid, trace_path=tmp_path / "invalid.jsonl")
    assert result.status == "needs_human"
    assert "invalid finding format" in result.ask_you[0]


def test_offline_cache_miss_and_model_error_are_clear(tmp_path: Path) -> None:
    common = dict(
        changes=[_change()], rule_findings=[], documents=load_corpus(FIXTURES),
        trace_dir=tmp_path / "traces", cache_dir=tmp_path / "cache",
        permissions_path=POLICY, schema_path=SCHEMA,
    )
    missing = research_changes(**common)
    assert missing.status == "needs_human"
    assert missing.ai_calls == 0
    assert "No usable offline Scholar response" in missing.ask_you[0]

    class ModelErrorResponses:
        def create(self, **_: object) -> None:
            error = RuntimeError("unavailable")
            error.status_code = 404
            raise error

    with pytest.raises(ScholarModelUnavailable, match="argus.toml"):
        research_changes(**common, live=True, client=SimpleNamespace(responses=ModelErrorResponses()))

    class ServiceErrorResponses:
        def create(self, **_: object) -> None:
            raise RuntimeError("synthetic-secret-in-error")

    failed = research_changes(
        **common, live=True, client=SimpleNamespace(responses=ServiceErrorResponses()),
        run_id="api-failed",
    )
    assert failed.status == "needs_human"
    assert failed.ai_calls == 1
    assert "synthetic-secret-in-error" not in (tmp_path / "traces" / "api-failed.jsonl").read_text(encoding="utf-8")
    assert "API request failed or timed out" in failed.ask_you[0]


def test_permission_policy_is_fail_closed_and_cache_redacts_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = load_policy(POLICY)
    assert decide_permission("search_corpus", "aws_db_instance", is_write=False, policy=policy).approved
    assert not decide_permission("write_rule", "aws_db_instance", is_write=True, policy=policy).approved
    assert not decide_permission("search_corpus", "aws_kms_key", is_write=False, policy=policy).approved
    assert not decide_permission("unknown", "aws_db_instance", is_write=False, policy=policy).approved
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-in-response")
    target = tmp_path / "cache.json"
    _write_cache(target, ({"output": [], "output_text": "synthetic-secret-in-response"},))
    assert "synthetic-secret-in-response" not in target.read_text(encoding="utf-8")
    assert "[REDACTED]" in target.read_text(encoding="utf-8")
    assert _redact_keys("synthetic-secret-in-response") == "[REDACTED]"
