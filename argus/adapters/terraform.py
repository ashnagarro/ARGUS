"""Adapt Terraform ``show -json`` plans to provider-neutral changes."""

import json
from pathlib import Path
from typing import Any, Mapping

from argus.models import Change


_CANONICAL_TYPES = {
    "aws_db_instance": "data_store",
    "aws_rds_cluster": "data_store",
    "aws_ebs_volume": "data_store",
    "aws_s3_bucket": "data_store",
    "aws_security_group": "network_ingress",
    "aws_security_group_rule": "network_ingress",
    "aws_vpc_security_group_ingress_rule": "network_ingress",
    "aws_s3_bucket_server_side_encryption_configuration": "encryption_config",
    "aws_backup_plan": "backup_config",
    "aws_db_parameter_group": "engine_config",
}


def _load_plan(source: str | Path | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source
    with Path(source).open(encoding="utf-8") as plan_file:
        plan = json.load(plan_file)
    if not isinstance(plan, dict):
        raise ValueError("Terraform plan JSON must be an object")
    return plan


def _state(value: Any, field: str, address: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{address}: {field} must be an object or null")
    return value


def _tags(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, str]:
    tags: dict[str, str] = {}
    # Use the planned state for updates; merging before and after would hide
    # tag removals from governance rules. Deletes retain the prior tags.
    state = after if after is not None else before
    if state is not None:
        for key in ("tags_all", "tags"):
            value = state.get(key)
            if isinstance(value, dict):
                tags.update({tag: text for tag, text in value.items()
                             if isinstance(tag, str) and isinstance(text, str)})
    return tags


def parse_plan(source: str | Path | Mapping[str, Any]) -> list[Change]:
    """Read Terraform resource_changes without exposing plan JSON to rules."""
    plan = _load_plan(source)
    resource_changes = plan.get("resource_changes", [])
    if not isinstance(resource_changes, list):
        raise ValueError("Terraform plan resource_changes must be a list")

    changes: list[Change] = []
    for item in resource_changes:
        if not isinstance(item, dict):
            raise ValueError("Terraform resource_changes entries must be objects")
        address = item.get("address")
        resource_type = item.get("type")
        change = item.get("change")
        if not isinstance(address, str) or not isinstance(resource_type, str) or not isinstance(change, dict):
            raise ValueError("Terraform resource change needs address, type and change")
        raw_actions = change.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions or not all(isinstance(action, str) for action in raw_actions):
            raise ValueError(f"{address}: actions must be a nonempty list of strings")
        actions = tuple(raw_actions)
        if actions == ("no-op",):
            continue
        before = _state(change.get("before"), "before", address)
        after = _state(change.get("after"), "after", address)
        raw_paths = change.get("replace_paths") or []
        if not isinstance(raw_paths, list) or not all(isinstance(path, list) for path in raw_paths):
            raise ValueError(f"{address}: replace_paths must be a list of paths")
        replace_paths = tuple(tuple(path) for path in raw_paths)
        changes.append(Change(
            address=address,
            resource_type=resource_type,
            canonical_type=_CANONICAL_TYPES.get(resource_type, resource_type),
            actions=actions,
            before=before,
            after=after,
            replace_paths=replace_paths,
            tags=_tags(before, after),
            is_replace="delete" in actions and "create" in actions,
        ))
    return changes
