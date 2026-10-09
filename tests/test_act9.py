"""Act 9 joins plan context and checks Scholar evidence without network calls."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from argus import cli, scholar
from argus.act9 import REPLICA_DOC_IDS, RESTORE_QUOTE
from argus.corpus import load_corpus
from argus.parse_plan import parse_plan
from argus.verify import verify_quote


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "plans" / "act9_cross_region_replica.json"


def _project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    for name in ("permissions.yaml", "exceptions.yaml"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    (tmp_path / "argus.toml").write_text(
        '[scholar]\nmodel = "gpt-6.1-sol"\n', encoding="utf-8",
    )
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for doc_id in REPLICA_DOC_IDS:
        (corpus / f"{doc_id}.md").write_bytes((ROOT / "corpus" / f"{doc_id}.md").read_bytes())
    plan = tmp_path / "replica.json"
    plan.write_bytes(FIXTURE.read_bytes())
    return plan


def _model(monkeypatch, quote: str = RESTORE_QUOTE) -> None:
    def create(**kwargs):
        change = json.loads(kwargs["input"][0]["content"].removeprefix("CHANGE: "))
        return SimpleNamespace(output=[], output_text=json.dumps({"findings": [{
            "id": "F9", "resource": change["address"],
            "change_type": "cross_region_replica_restore_limitation",
            "claim": "The new cross-Region replica prevents native restores on its source.",
            "evidence": [{"doc_id": REPLICA_DOC_IDS[0], "quote": quote}],
            "severity": "high",
            "recommended_action": "Review native restore requirements before creating the replica.",
            "confidence": "high",
        }]}))

    monkeypatch.setattr(scholar, "_live_client", lambda: SimpleNamespace(
        responses=SimpleNamespace(create=create)))


def test_fixture_exposes_source_option_and_region_to_scholar() -> None:
    changes = parse_plan(FIXTURE)
    assert len(changes) == 1
    replica = changes[0]
    assert replica.actions == ("create",)
    assert replica.after["replicate_source_db"] == "synthetic-sqlserver-source"
    assert replica.after["source_instance"]["engine"] == "sqlserver-ee"
    assert replica.after["source_instance"]["option_group_options"] == ["SQLSERVER_BACKUP_RESTORE"]
    assert replica.after["source_instance"]["region"] == "us-east-1"
    assert replica.after["replica_region"] == "us-west-2"
    assert replica.after["cross_region"] is True
    documents = load_corpus(ROOT / "corpus")
    assert "you can not perform native restores on the source DB instance until you delete all its cross-Region replicas" in documents[REPLICA_DOC_IDS[0]].body
    assert verify_quote(REPLICA_DOC_IDS[0], RESTORE_QUOTE, documents).verified


def test_mocked_verified_quote_adds_conditions_and_unknown_quote_does_not(tmp_path: Path, monkeypatch) -> None:
    plan = _project(tmp_path, monkeypatch)
    _model(monkeypatch)
    assert cli.run_check(plan, scholar_mode="live", governance_enabled=False,
                         team_enabled=False, emit_output=False) == 0
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert record["verdict"] == "GO-WITH-CONDITIONS"
    assert record["ai_findings"][0]["verified"] is True
    assert record["ai_findings"][0]["evidence"][0]["quote"] == RESTORE_QUOTE
    assert record["rule_findings"] == []

    _model(monkeypatch, "This fabricated sentence is not present in either local AWS guide.")
    assert cli.run_check(plan, scholar_mode="live", governance_enabled=False,
                         team_enabled=False, emit_output=False) == 0
    record = json.loads((tmp_path / ".cache" / "last_run.json").read_text(encoding="utf-8"))
    assert record["verdict"] == "GO"
    assert record["ai_findings"][0]["verified"] is False
    assert record["ai_findings"][0]["verification_reason"] == "quote_not_found"


def test_same_region_replica_context_is_not_cross_region(tmp_path: Path) -> None:
    plan = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan["configuration"]["root_module"]["resources"][-1]["provider_config_key"] = "aws"
    path = tmp_path / "same-region.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert parse_plan(path)[0].after["cross_region"] is False
