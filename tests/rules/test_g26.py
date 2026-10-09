"""G26 scans Terraform source without exposing the literal value."""

from argus.governance import GovernanceContext
from argus.rules.g26 import HardcodedTerraformSecret


def test_literal_secret_triggers_without_echoing_value(tmp_path) -> None:
    source = tmp_path / "main.tf"
    source.write_text('password = "synthetic-secret-value"\n', encoding="utf-8")
    findings = HardcodedTerraformSecret().check_context((), GovernanceContext(tf_files=(source,)))
    assert len(findings) == 1 and findings[0].rule_id == "G26"
    assert "synthetic-secret-value" not in findings[0].message


def test_variable_reference_does_not_trigger(tmp_path) -> None:
    source = tmp_path / "main.tf"
    source.write_text("password = var.synthetic_password\n", encoding="utf-8")
    assert HardcodedTerraformSecret().check_context((), GovernanceContext(tf_files=(source,))) == []
