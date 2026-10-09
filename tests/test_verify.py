"""Phase 5 quote verification uses only synthetic local documents."""

from pathlib import Path

from argus.corpus import load_corpus
from argus.verify import verify_finding, verify_quote


TEST_CORPUS = Path(__file__).parent / "fixtures" / "corpus"
ALPHA_QUOTE = (
    "Before replacing the fictional database, copy its sample records "
    "to a separate test snapshot."
)
BETA_QUOTE = (
    "Enable encryption for the imaginary storage bucket before saving "
    "its sample objects."
)


def test_exact_quote_is_verified_with_local_metadata() -> None:
    documents = load_corpus(TEST_CORPUS)

    result = verify_quote("synthetic-alpha", ALPHA_QUOTE, documents)

    assert result.verified
    assert result.reason is None
    assert result.evidence[0]["doc_id"] == "synthetic-alpha"
    assert result.evidence[0]["url"] == documents["synthetic-alpha"].url
    assert result.evidence[0]["retrieved_at"] == documents["synthetic-alpha"].retrieved_at


def test_only_whitespace_may_change_in_an_exact_quote() -> None:
    documents = load_corpus(TEST_CORPUS)
    spaced_quote = ALPHA_QUOTE.replace("copy its sample", "copy\n  its sample")

    assert verify_quote("synthetic-alpha", spaced_quote, documents).verified
    assert verify_quote(
        "synthetic-alpha", ALPHA_QUOTE.replace("copy", "move"), documents
    ).reason == "quote_not_found"


def test_quote_from_another_document_is_rejected() -> None:
    documents = load_corpus(TEST_CORPUS)

    assert verify_quote("synthetic-alpha", BETA_QUOTE, documents).reason == "quote_not_found"


def test_short_quote_is_rejected() -> None:
    documents = load_corpus(TEST_CORPUS)

    assert verify_quote("synthetic-alpha", "fictional database", documents).reason == "quote_too_short"


def test_missing_document_is_rejected() -> None:
    documents = load_corpus(TEST_CORPUS)

    assert verify_quote("missing-doc", ALPHA_QUOTE, documents).reason == "doc_not_found"


def test_every_quote_must_pass_and_ai_url_is_ignored() -> None:
    documents = load_corpus(TEST_CORPUS)
    valid_evidence = [
        {"doc_id": "synthetic-alpha", "quote": ALPHA_QUOTE, "url": "https://untrusted.invalid"},
        {"doc_id": "synthetic-beta", "quote": BETA_QUOTE},
    ]

    result = verify_finding(valid_evidence, documents)

    assert result.verified
    assert result.evidence[0]["url"] == documents["synthetic-alpha"].url
    assert result.evidence[0]["url"] != "https://untrusted.invalid"
    assert verify_finding(valid_evidence + [{"doc_id": "synthetic-beta", "quote": ALPHA_QUOTE}], documents).verified is False
    assert verify_finding([], documents).verified is False
