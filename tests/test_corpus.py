"""Tests for the local reference document loader and section search."""

from pathlib import Path
from unittest.mock import patch

import pytest

from argus.corpus import load_corpus, read_section, search_corpus


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "corpus"


def test_loads_front_matter_and_numbered_sections() -> None:
    documents = load_corpus(FIXTURE_DIR)

    assert set(documents) == {"synthetic-alpha", "synthetic-beta"}
    alpha = documents["synthetic-alpha"]
    assert alpha.url == "https://example.invalid/synthetic-alpha"
    assert alpha.retrieved_at == "2026-10-09"
    assert "Before replacing the fictional database" in alpha.body
    assert [section.heading for section in alpha.sections] == [
        "SYNTHETIC TEST DOCUMENT",
        "Database replacement",
        "Database recovery",
    ]
    assert read_section("synthetic-alpha", 2, documents).text.startswith(
        "Before replacing the fictional database"
    )


def test_search_ranks_relevant_section_and_limits_results() -> None:
    documents = load_corpus(FIXTURE_DIR)

    matches = search_corpus("database replacement snapshot", documents)
    assert matches[0].heading == "Database replacement"
    assert len(search_corpus("database", documents, limit=1)) == 1
    assert search_corpus("unmentionedterm", documents) == []
    assert search_corpus("database", documents, limit=0) == []


def test_rejects_missing_metadata() -> None:
    content = "---\ndoc_id: synthetic-invalid\nurl: https://example.invalid/invalid\n---\n# Heading\n"

    with patch.object(Path, "glob", return_value=[Path("invalid.md")]), patch.object(
        Path, "read_text", return_value=content
    ):
        with pytest.raises(ValueError, match="retrieved_at"):
            load_corpus(FIXTURE_DIR)


def test_rejects_duplicate_doc_id() -> None:
    content = (
        "---\ndoc_id: duplicate\nurl: https://example.invalid/test\n"
        "retrieved_at: 2026-10-09\n---\n# Heading\nText.\n"
    )

    with patch.object(
        Path, "glob", return_value=[Path("first.md"), Path("second.md")]
    ), patch.object(Path, "read_text", return_value=content):
        with pytest.raises(ValueError, match="duplicate doc_id"):
            load_corpus(FIXTURE_DIR)


def test_read_missing_section_raises_key_error() -> None:
    documents = load_corpus(FIXTURE_DIR)

    with pytest.raises(KeyError):
        read_section("synthetic-beta", 99, documents)
