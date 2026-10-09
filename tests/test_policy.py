"""Policy compilation tests use fake subprocesses; no test calls Codex."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess

import pytest

from argus import cli, policy
from argus.console import write_console


SENTENCE = "Database instances in production must have deletion protection enabled."


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for folder in ("argus/rules", "tests/rules", "ledger", "examples/agent-demo"):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "argus/rules/r007.py").write_text("# existing rule\n", encoding="utf-8")
    permissions = Path(__file__).resolve().parents[1] / "permissions.yaml"
    (tmp_path / "permissions.yaml").write_bytes(permissions.read_bytes())
    monkeypatch.setenv("CODEX_API_KEY", "policy-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "other-test-key")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "inherited-home"))
    return tmp_path


def _generated(root: Path, *, source: str = SENTENCE) -> None:
    approved_on = datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()
    (root / "argus/rules/r008.py").write_text(
        '"""Implements a human-supplied policy."""\n'
        'from argus.rules import Rule\n'
        'class PolicyRule(Rule):\n'
        '    id = "R008"\n'
        f'    source_policy = {source!r}\n'
        f'    human_approved_on = "{approved_on}"\n'
        '    title = "Production deletion protection"\n'
        '    severity = "high"\n'
        '    why_it_matters = "A production database might be deleted."\n'
        '    how_to_fix = "Set deletion_protection = true."\n'
        '    def check(self, change, all_changes):\n'
        '        return [self.finding(change, "protection disabled")] if '
        'change.resource_type == "aws_db_instance" and '
        'change.tags.get("env") == "prod" and '
        'change.after.get("deletion_protection") is False else []\n',
        encoding="utf-8",
    )
    (root / "tests/rules/test_r008.py").write_text(
        'from argus.rules.r008 import PolicyRule\n'
        'from argus.models import Change\n'
        'def _change(protection):\n'
        '    return Change("aws_db_instance.fake", "aws_db_instance", '
        '"database_instance", ("update",), {}, '
        '{"deletion_protection": protection}, (), {"env": "prod"}, False)\n'
        'def test_policy_triggers():\n'
        '    assert PolicyRule().check(_change(False), [])\n'
        'def test_policy_does_not_trigger():\n'
        '    assert not PolicyRule().check(_change(True), [])\n',
        encoding="utf-8",
    )


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_policy_compiles_with_one_approval_and_positive_negative_tests(project: Path) -> None:
    commands: list[list[str]] = []
    environments: list[dict[str, str]] = []
    prompts: list[str] = []
    approvals: list[str] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        environments.append(dict(kwargs["env"]))  # type: ignore[arg-type]
        if command[0] == "custom-codex":
            prompts.append(str(kwargs["input"]))
            _generated(project)
            return subprocess.CompletedProcess(command, 0, "policy-test-key", "")
        return subprocess.CompletedProcess(command, 0, "2 passed", "")

    result = policy.compile_policy(
        SENTENCE, project, approve=lambda action: approvals.append(action) or True,
        codex_executable="custom-codex", run_id="policy-success", runner=runner,
    )

    assert result.status == "compiled" and result.rule_id == "R008"
    assert result.attempts == 1 and len(approvals) == 1
    assert commands[0][:4] == ["custom-codex", "exec", "-c", 'model_reasoning_effort="high"']
    assert commands[0][4:8] == ["-s", "workspace-write", "-C", str(project)]
    assert "POLICY_JSON" in prompts[0] and SENTENCE in prompts[0]
    assert "CODEX_HOME" not in environments[0]
    assert "OPENAI_API_KEY" not in environments[0]
    assert not any(name.endswith("API_KEY") for name in environments[1])
    assert commands[1][-1] == "tests/rules/test_r008.py"
    assert "policy-test-key" not in result.trace_path.read_text(encoding="utf-8")
    assert "other-test-key" not in result.trace_path.read_text(encoding="utf-8")
    events = _events(result.trace_path)
    assert any(item.get("event") == "human_approval" and item.get("granted") for item in events)
    assert any(item.get("event") == "tool_result" and item.get("tool") == "pytest"
               and item.get("exit_code") == 0 for item in events)
    assert '"status": "compiled"' in (project / "ledger/ledger.jsonl").read_text(encoding="utf-8")
    console = write_console(project).read_text(encoding="utf-8")
    assert "human policy" in console
    assert "Human-supplied policy (no corpus citation)" in console


def test_denied_approval_never_calls_codex(project: Path) -> None:
    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("Codex ran without approval")

    result = policy.compile_policy(
        SENTENCE, project, approve=lambda action: False,
        run_id="policy-denied", runner=runner,
    )
    assert result.status == "needs human" and result.attempts == 0
    assert not (project / "argus/rules/r008.py").exists()
    assert any(item.get("event") == "human_approval" and item.get("granted") is False
               for item in _events(result.trace_path))


def test_scope_rollback_leaves_agent_demo_untouched(project: Path) -> None:
    readme = project / "README.md"
    readme.write_text("before\n", encoding="utf-8")
    lockfile = project / "examples/agent-demo/.terraform.lock.hcl"

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        _generated(project)
        readme.write_text("outside scope\n", encoding="utf-8")
        lockfile.write_text("user-created lockfile\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = policy.compile_policy(
        SENTENCE, project, approve=lambda action: True,
        run_id="policy-scope", runner=runner,
    )
    assert result.status == "needs human" and result.attempts == 1
    assert readme.read_text(encoding="utf-8") == "before\n"
    assert not (project / "argus/rules/r008.py").exists()
    assert not (project / "tests/rules/test_r008.py").exists()
    assert lockfile.read_text(encoding="utf-8") == "user-created lockfile\n"


def test_failing_test_retries_with_failure_context(project: Path) -> None:
    attempts = 0
    prompts: list[str] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal attempts
        if command[0] == "codex":
            prompts.append(str(kwargs["input"]))
            _generated(project)
            return subprocess.CompletedProcess(command, 0, "", "")
        attempts += 1
        return subprocess.CompletedProcess(
            command, 1 if attempts == 1 else 0,
            "synthetic failure" if attempts == 1 else "2 passed", "",
        )

    result = policy.compile_policy(
        SENTENCE, project, approve=lambda action: True,
        run_id="policy-retry", runner=runner,
    )
    assert result.status == "compiled" and result.attempts == 2
    assert len(prompts) == 2 and "synthetic failure" in prompts[1]


def test_three_failures_restore_generated_files(project: Path) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "codex":
            _generated(project)
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "synthetic failure", "")

    result = policy.compile_policy(
        SENTENCE, project, approve=lambda action: True,
        run_id="policy-three", runner=runner,
    )
    assert result.status == "needs human" and result.attempts == 3
    assert not (project / "argus/rules/r008.py").exists()
    assert not (project / "tests/rules/test_r008.py").exists()


def test_generated_rule_must_retain_exact_source_policy(project: Path) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        _generated(project, source="a different policy")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = policy.compile_policy(
        SENTENCE, project, approve=lambda action: True,
        run_id="policy-source", runner=runner,
    )
    assert result.status == "needs human" and result.attempts == 3
    assert "exact source policy" in (result.reason or "")
    assert not (project / "argus/rules/r008.py").exists()


def test_cli_flag_disables_policy_without_writes(project: Path, monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", project)
    (project / "argus.toml").write_text("[flags]\npolicy_compiler = false\n", encoding="utf-8")
    assert cli.main(["policy", SENTENCE]) == 2
    assert "enable [flags] policy_compiler" in capsys.readouterr().err
    assert not (project / "ledger/ledger.jsonl").exists()


def test_cli_enabled_policy_uses_smith_settings(project: Path, monkeypatch: pytest.MonkeyPatch,
                                                capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", project)
    (project / "argus.toml").write_text(
        '[smith]\ncodex_executable = "custom-codex"\ncodex_home = ".codex-home"\n'
        '[flags]\npolicy_compiler = true\n', encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_approve_smith_write", lambda action: True)
    called: dict[str, object] = {}

    def fake_compile(sentence: str, root: Path, **kwargs: object) -> policy.PolicyResult:
        called.update(sentence=sentence, root=root, **kwargs)
        return policy.PolicyResult("compiled", "R008", 1, None, project / "trace.jsonl")

    monkeypatch.setattr(policy, "compile_policy", fake_compile)
    assert cli.main(["policy", SENTENCE]) == 0
    assert called["sentence"] == SENTENCE and called["root"] == project
    assert called["codex_executable"] == "custom-codex"
    assert called["codex_home"] == ".codex-home"
    assert "Compiled R008" in capsys.readouterr().out


def test_invalid_sentence_is_rejected_before_approval(project: Path) -> None:
    with pytest.raises(ValueError, match="one line"):
        policy.compile_policy("short", project, approve=lambda action: pytest.fail("approval asked"))
