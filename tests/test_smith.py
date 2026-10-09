"""Smith tests use a fake subprocess; they never invoke Codex or an API."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess

import pytest

from argus.models import AIFinding, RuleFinding
from argus import smith


QUOTE = (
    "SYNTHETIC TEST DOCUMENT: A major engine upgrade requires a matching "
    "parameter group family."
)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for folder in ("argus/rules", "tests/rules", "corpus", "ledger", "fixtures/plans"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "argus/rules/r006.py").write_text("# existing rule\n", encoding="utf-8")
    (tmp_path / "corpus/synthetic.md").write_text(
        "---\ndoc_id: synthetic\nurl: https://example.test/synthetic\n"
        "retrieved_at: 2026-10-09\n---\n" + QUOTE + "\n",
        encoding="utf-8",
    )
    policy = Path(__file__).resolve().parents[1] / "permissions.yaml"
    (tmp_path / "permissions.yaml").write_bytes(policy.read_bytes())
    monkeypatch.setenv("CODEX_API_KEY", "smith-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "scholar-test-key")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "inherited-untrusted-home"))
    monkeypatch.setattr(smith, "parse_plan", lambda path: path.name)
    monkeypatch.setattr(smith, "run_rules", lambda fixture: [] if fixture == "clean_change.json" else [
        RuleFinding(
            "R007",
            "aws_db_instance.billing" if fixture == "act3_major_upgrade_second.json"
            else "aws_db_instance.orders",
            "Synthetic rule", "high", "caught",
        ),
    ])
    return tmp_path


def finding(*, verified: bool = True) -> AIFinding:
    return AIFinding(
        id="AI-01",
        resource="aws_db_instance.orders",
        claim="Synthetic major upgrade claim",
        severity="high",
        recommended_action="Choose a matching parameter group.",
        verified=verified,
        evidence=({"doc_id": "synthetic", "quote": QUOTE},),
        change_type="update",
        confidence="high",
    )


def write_generated(project: Path) -> None:
    (project / "argus/rules/r007.py").write_text(
        '"""R007: synthetic, retrieved_at 2026-10-09."""\n',
        encoding="utf-8",
    )
    (project / "tests/rules/test_r007.py").write_text(
        '"""act2_major_upgrade.json and clean_change.json."""\n'
        "def test_positive(): pass\n"
        "def test_negative(): pass\n",
        encoding="utf-8",
    )


def trace_events(project: Path, run_id: str) -> list[dict[str, object]]:
    trace = project / "ledger/traces" / f"{run_id}.jsonl"
    return [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]


def test_compiles_with_approval_high_reasoning_and_zero_ai_calls(project: Path) -> None:
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []
    approvals: list[str] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        environments.append(dict(kwargs["env"]))  # type: ignore[arg-type]
        if command[0] == "custom-codex":
            write_generated(project)
            return subprocess.CompletedProcess(command, 0, "smith-test-key", "")
        return subprocess.CompletedProcess(command, 0, "2 passed", "")

    result = smith.compile_finding(
        finding(), project, approve=lambda action: approvals.append(action) or True,
        codex_executable="custom-codex", run_id="smith-success", runner=runner,
    )

    assert result.status == "compiled"
    assert result.rule_id == "R007"
    assert result.attempts == 1
    assert result.after_ai_calls == 0
    assert len(approvals) == 1
    assert commands[0][:4] == ["custom-codex", "exec", "-c", 'model_reasoning_effort="high"']
    assert commands[0][4:8] == ["-s", "workspace-write", "-C", str(project)]
    assert "CODEX_HOME" not in environments[0]
    assert environments[0]["CODEX_API_KEY"] == "smith-test-key"
    assert "OPENAI_API_KEY" not in environments[0]
    assert not any(name.endswith("API_KEY") for name in environments[1])
    trace_text = result.trace_path.read_text(encoding="utf-8")
    assert "smith-test-key" not in trace_text
    assert "scholar-test-key" not in trace_text
    events = trace_events(project, "smith-success")
    assert any(event.get("event") == "permission_decision"
               and event.get("decision") == "requires_human_approval" for event in events)
    assert any(event.get("event") == "act3_confirmation" and event.get("caught") is True
               for event in events)
    assert any(event.get("event") == "act3_confirmation"
               and event.get("act2_caught") is True
               and event.get("clean_caught") is False for event in events)
    ledger = (project / "ledger/ledger.jsonl").read_text(encoding="utf-8")
    assert '"status": "compiled"' in ledger
    assert "smith-test-key" not in ledger


def test_denied_approval_never_runs_codex(project: Path) -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Codex was called without human approval")

    result = smith.compile_finding(
        finding(), project, approve=lambda action: False,
        run_id="smith-denied", runner=runner,
    )
    assert result.status == "needs human"
    assert result.attempts == 0
    assert not (project / "argus/rules/r007.py").exists()
    assert any(event.get("event") == "human_approval" and event.get("granted") is False
               for event in trace_events(project, "smith-denied"))


def test_out_of_scope_change_is_rolled_back(project: Path) -> None:
    readme = project / "README.md"
    readme.write_text("before\n", encoding="utf-8")

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        write_generated(project)
        readme.write_text("after\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = smith.compile_finding(
        finding(), project, approve=lambda action: True,
        run_id="smith-scope", runner=runner,
    )
    assert result.status == "needs human"
    assert result.attempts == 1
    assert readme.read_text(encoding="utf-8") == "before\n"
    assert not (project / "argus/rules/r007.py").exists()
    assert not (project / "tests/rules/test_r007.py").exists()
    assert any("README.md" in event.get("violations", [])
               for event in trace_events(project, "smith-scope")
               if event.get("event") == "scope_check")


def test_retries_failed_test_and_passes_failure_to_codex(project: Path) -> None:
    prompts: list[str] = []
    tests = 0

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal tests
        if command[0] == "codex":
            prompts.append(str(kwargs["input"]))
            write_generated(project)
            return subprocess.CompletedProcess(command, 0, "", "")
        tests += 1
        if tests == 1:
            return subprocess.CompletedProcess(command, 1, "synthetic assertion failed", "")
        return subprocess.CompletedProcess(command, 0, "2 passed", "")

    approvals = 0

    def approve(action: str) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    result = smith.compile_finding(
        finding(), project, approve=approve, run_id="smith-retry", runner=runner,
    )
    assert result.status == "compiled"
    assert result.attempts == 2
    assert approvals == 1
    assert len([event for event in trace_events(project, "smith-retry")
                if event.get("event") == "permission_decision"]) == 1
    assert len(prompts) == 2
    assert "synthetic assertion failed" in prompts[1]


def test_three_failed_attempts_return_needs_human_and_restore(project: Path) -> None:
    calls = 0

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        if command[0] == "codex":
            calls += 1
            write_generated(project)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "synthetic test failure", "")

    result = smith.compile_finding(
        finding(), project, approve=lambda action: True,
        run_id="smith-three", runner=runner,
    )
    assert result.status == "needs human"
    assert result.attempts == 3
    assert calls == 3
    assert "synthetic test failure" in (result.reason or "")
    assert not (project / "argus/rules/r007.py").exists()
    assert not (project / "tests/rules/test_r007.py").exists()


def test_success_without_file_changes_reports_read_only_once(project: Path) -> None:
    calls = 0
    approvals = 0

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        assert "-s" in command and command[command.index("-s") + 1] == "workspace-write"
        assert 'model_reasoning_effort="high"' in command
        return subprocess.CompletedProcess(command, 0, "Workspace is read-only", "")

    def approve(action: str) -> bool:
        nonlocal approvals
        approvals += 1
        return True

    result = smith.compile_finding(
        finding(), project, approve=approve, run_id="smith-read-only", runner=runner,
    )
    assert result.status == "needs human"
    assert result.attempts == 1
    assert result.reason == "codex ran read-only (project not trusted or sandbox restricted)"
    assert calls == approvals == 1
    assert any(event.get("event") == "attempt_failure" and event.get("reason") == result.reason
               for event in trace_events(project, "smith-read-only"))


def test_configured_codex_home_is_passed_to_runner(project: Path) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["env"]["CODEX_HOME"] == str(project / ".codex-home")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = smith.compile_finding(
        finding(), project, approve=lambda action: True,
        codex_home=".codex-home", run_id="smith-configured-home", runner=runner,
    )
    assert result.status == "needs human"


def test_unverified_finding_is_never_sent_to_codex(project: Path) -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Unverified finding reached Codex")

    result = smith.compile_finding(
        finding(verified=False), project, approve=lambda action: True,
        run_id="smith-unverified", runner=runner,
    )
    assert result.status == "needs human"
    assert result.attempts == 0
    assert "VERIFIED" in (result.reason or "")
