"""Redact Terraform state values before they reach rules or Scholar."""

from __future__ import annotations

import re
from typing import Any


REDACTED = "[REDACTED]"

# Keep configuration switches such as enable_key_rotation usable by rules.
# Credential-bearing string fields, including provider key identifiers, are
# removed even when Terraform omitted a sensitivity mask.
_SENSITIVE_NAME = re.compile(
    r"(?i)(?:password|passwd|secret|credential|private[_-]?key|"
    r"api[_-]?key|access[_-]?key|session[_-]?key|"
    r"(?:^|[_-])key(?:$|[_-])|(?:^|[_-])token(?:$|[_-])|authorization)"
)
_CREDENTIAL_VALUE = re.compile(
    r"(?i)(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:sk|rk|pk|sess)[-_][A-Za-z0-9_.*…-]{8,})"
)


def redact_value(value: Any, sensitivity: Any = None, *, field: str = "") -> Any:
    """Return a copy of a JSON value with sensitive leaves replaced.

    Terraform's before_sensitive/after_sensitive shape mirrors the state: a
    true boolean marks the corresponding value, including an entire subtree.
    Field-name checks cover plans that omit those masks. Numeric and boolean
    settings remain available to deterministic rules unless Terraform marked
    them sensitive.
    """
    if sensitivity is True:
        return REDACTED
    if isinstance(value, dict):
        mask = sensitivity if isinstance(sensitivity, dict) else {}
        return {
            key: redact_value(item, mask.get(key), field=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        mask = sensitivity if isinstance(sensitivity, (list, dict)) else ()
        return [
            redact_value(item,
                         mask[index] if isinstance(mask, list) and index < len(mask)
                         else mask.get(str(index)) if isinstance(mask, dict) else None,
                         field=field)
            for index, item in enumerate(value)
        ]
    if isinstance(value, str) and (_SENSITIVE_NAME.search(field)
                                    or _CREDENTIAL_VALUE.search(value)):
        return REDACTED
    return value
