"""Verify AI evidence against the local document corpus."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .corpus import Document


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Code-checked evidence and its status."""

    verified: bool
    reason: str | None
    evidence: tuple[dict[str, str], ...] = ()


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def verify_quote(
    doc_id: str, quote: str, documents: Mapping[str, Document]
) -> VerificationResult:
    """Verify one quote, attaching source metadata only from the local document."""
    document = documents.get(doc_id)
    if document is None:
        return VerificationResult(False, "doc_not_found")
    if not isinstance(quote, str):
        return VerificationResult(False, "quote_not_found")
    normalized_quote = _normalize_whitespace(quote)
    if len(normalized_quote) < 40:
        return VerificationResult(False, "quote_too_short")
    if normalized_quote not in _normalize_whitespace(document.body):
        return VerificationResult(False, "quote_not_found")
    return VerificationResult(
        True,
        None,
        ({
            "doc_id": document.doc_id,
            "quote": quote,
            "url": document.url,
            "retrieved_at": document.retrieved_at,
        },),
    )


def verify_finding(
    evidence: Sequence[Mapping[str, str]], documents: Mapping[str, Document]
) -> VerificationResult:
    """A claim is verified only if it has evidence and every quote passes."""
    if not evidence:
        return VerificationResult(False, "quote_not_found")
    checked: list[dict[str, str]] = []
    for item in evidence:
        result = verify_quote(item.get("doc_id", ""), item.get("quote", ""), documents)
        if not result.verified:
            return VerificationResult(False, result.reason, tuple(checked))
        checked.extend(result.evidence)
    return VerificationResult(True, None, tuple(checked))
