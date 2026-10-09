"""Offline replay setup for the cross-Region SQL Server replica demonstration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

from .corpus import Document
from .models import Change


REPLICA_DOC_IDS = ("rds-sqlserver-read-replicas", "rds-sqlserver-byom")
RESTORE_QUOTE = (
    "The source DB instance of a SQL Server cross-Region replica can have the "
    "SQLSERVER_BACKUP_RESTORE option, but you can not perform native restores on "
    "the source DB instance until you delete all its cross-Region replicas."
)


def seed_replica_demo_replay(
    changes: Sequence[Change], documents: Mapping[str, Document], *,
    model: str, schema_path: Path, cache_dir: Path,
) -> None:
    """Prepare a synthetic Scholar response for an offline-only Act 9 demo."""
    from .scholar import _cache_key, _write_cache

    guide = documents.get(REPLICA_DOC_IDS[0])
    if guide is None:
        raise ValueError("fetch the SQL Server replica guide with argus corpus fetch")
    section = next((item for item in guide.sections if RESTORE_QUOTE in item.text), None)
    if section is None:
        raise ValueError("Act 9 demo quote is absent from the fetched replica guide")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for change in changes:
        context = change.after or {}
        source = context.get("source_instance") or {}
        if not (context.get("cross_region") and
                "SQLSERVER_BACKUP_RESTORE" in source.get("option_group_options", [])):
            continue
        cache_path = cache_dir / f"{_cache_key(change, documents, model, schema)}.json"
        if cache_path.is_file():
            continue
        calls = (
            ("get_change", {}),
            ("search_corpus", {"query": "SQL Server cross-Region replica native restore source option"}),
            ("read_section", {"doc_id": guide.doc_id, "number": section.number}),
            ("verify_quote", {"doc_id": guide.doc_id, "quote": RESTORE_QUOTE}),
        )
        records = [
            {"output": [{"type": "function_call", "name": name,
                         "arguments": json.dumps(arguments), "call_id": f"act9-{index}"}],
             "output_text": ""}
            for index, (name, arguments) in enumerate(calls, 1)
        ]
        records.append({"output": [], "output_text": json.dumps({"findings": [{
            "id": "F9", "resource": change.address,
            "change_type": "cross_region_replica_restore_limitation",
            "claim": "A cross-Region replica blocks native restores on its SQL Server source.",
            "evidence": [{"doc_id": guide.doc_id, "quote": RESTORE_QUOTE}],
            "severity": "high",
            "recommended_action": (
                "Review restore requirements before creating the cross-Region replica; "
                "native restores on the source require deleting all cross-Region replicas."
            ),
            "confidence": "high",
        }]})})
        _write_cache(cache_path, tuple(records))
