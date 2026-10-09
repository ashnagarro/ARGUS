"""The staged OpenAI diagnostic is tested without any network calls."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from argus.agent_loop import TOOLS
from scripts.check_openai import check_openai, main


ROOT = Path(__file__).resolve().parents[1]


class FakeResponses:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = iter(outcomes)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(models: list[str], outcomes: list[object]) -> SimpleNamespace:
    return SimpleNamespace(
        models=SimpleNamespace(list=lambda: SimpleNamespace(data=[SimpleNamespace(id=model) for model in models])),
        responses=FakeResponses(outcomes),
    )


def _strict_objects(schema: dict[str, object]) -> None:
    if schema.get("type") == "object":
        properties = schema["properties"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(properties)
        for child in properties.values():
            _strict_objects(child)
    elif schema.get("type") == "array":
        _strict_objects(schema["items"])


def test_probe_uses_real_scholar_schema_and_tools_in_isolated_requests() -> None:
    client = _client(["gpt-6.1-sol", "gpt-6-luna"], [SimpleNamespace(status="completed")] * 4)
    output = StringIO()

    assert check_openai(client=client, root=ROOT, output=output) == 0

    calls = client.responses.calls
    assert len(calls) == 4
    assert calls[0] == {"model": "gpt-6.1-sol", "input": "Reply OK."}
    assert set(calls[1]) == {"model", "input", "text"}
    text = calls[1]["text"]
    assert text["format"]["type"] == "json_schema"
    assert text["format"]["strict"] is True
    _strict_objects(text["format"]["schema"])
    assert set(calls[2]) == {"model", "input", "tools"}
    assert calls[2]["tools"] is TOOLS
    for tool in TOOLS:
        assert tool["type"] == "function"
        assert tool["strict"] is True
        _strict_objects(tool["parameters"])
    assert calls[3]["tools"] is TOOLS
    assert calls[3]["text"] is text
    assert calls[3]["parallel_tool_calls"] is False
    assert calls[3]["store"] is False
    assert calls[3]["include"] == ["reasoning.encrypted_content"]
    assert calls[3]["timeout"] == 30.0
    assert calls[3]["input"] == [{"role": "user", "content": 'Return {"findings": []}.'}]
    assert "All five probes succeeded" in output.getvalue()


def test_probe_stops_if_configured_model_is_absent() -> None:
    client = _client(["gpt-6-luna"], [])
    output = StringIO()

    assert check_openai(client=client, root=ROOT, output=output) == 1
    assert "configured model is absent" in output.getvalue()
    assert "gpt-6-luna" in output.getvalue()
    assert client.responses.calls == []


def test_probe_rejects_empty_configured_model(tmp_path: Path) -> None:
    (tmp_path / "argus.toml").write_text('[scholar]\nmodel = ""\n', encoding="utf-8")
    client = _client([], [])
    output = StringIO()

    assert check_openai(client=client, root=tmp_path, output=output) == 1
    assert "nonempty string" in output.getvalue()
    assert client.responses.calls == []


def test_probe_runs_all_isolated_stages_and_redacts_error_message_and_body(monkeypatch) -> None:
    fake_key = "sk-" + "proj-" + "A" * 50
    other_key = "sk-" + "other-" + "B" * 50
    monkeypatch.setenv("OPENAI_API_KEY", fake_key)
    error = RuntimeError(f"schema rejected: {fake_key}")
    error.status_code = 400
    error.body = {"error": {"message": f"invalid schema {other_key}"}, "api_key": "arbitrary-token"}
    client = _client(
        ["gpt-6.1-sol"],
        [SimpleNamespace(status="completed"), error, SimpleNamespace(status="completed")],
    )
    output = StringIO()

    assert check_openai(client=client, root=ROOT, output=output) == 1

    diagnostic = output.getvalue()
    assert "RuntimeError" in diagnostic
    assert "HTTP 400" in diagnostic
    assert "schema rejected" in diagnostic
    assert "invalid schema" in diagnostic
    assert fake_key not in diagnostic
    assert other_key not in diagnostic
    assert "arbitrary-token" not in diagnostic
    assert "[REDACTED]" in diagnostic
    assert len(client.responses.calls) == 3
    assert "4. Responses call with only Scholar tool definitions" in diagnostic
    assert "5. Combined Scholar request shape: SKIPPED" in diagnostic


def test_probe_reports_multiple_isolated_failures_before_skipping_combined() -> None:
    client = _client(
        ["gpt-6.1-sol"],
        [RuntimeError("basic rejected"), RuntimeError("schema rejected"), RuntimeError("tools rejected")],
    )
    output = StringIO()

    assert check_openai(client=client, root=ROOT, output=output) == 1

    diagnostic = output.getvalue()
    assert len(client.responses.calls) == 3
    assert "basic rejected" in diagnostic
    assert "schema rejected" in diagnostic
    assert "tools rejected" in diagnostic
    assert diagnostic.count("FAILED:") == 3
    assert "5. Combined Scholar request shape: SKIPPED" in diagnostic


def test_main_without_key_does_not_construct_client(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main() == 1
    assert "OPENAI_API_KEY is missing" in capsys.readouterr().err
