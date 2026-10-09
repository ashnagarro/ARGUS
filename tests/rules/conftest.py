"""Synthetic resource builder for governance context tests."""

from __future__ import annotations

from typing import Any

import pytest

from argus.models import Change


@pytest.fixture
def governance_change():
    def make(
        *, resource_type: str = "aws_db_instance",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> Change:
        return Change(
            address=f"{resource_type}.synthetic", resource_type=resource_type,
            canonical_type=resource_type, actions=("update",),
            before=before, after=after if after is not None else {},
            replace_paths=(), tags=tags or {}, is_replace=False,
        )
    return make
