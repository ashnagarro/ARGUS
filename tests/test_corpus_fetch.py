"""Offline tests for mechanical extraction and multi-source corpus fetching."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

import argus.corpus_fetch as corpus_fetch
from argus.corpus_fetch import extract_main_content, fetch_corpus


SAMPLE_HTML = Path(__file__).parent / "fixtures" / "corpus" / "sample_article.html"


def test_extract_main_content_preserves_article_structure_only() -> None:
    html = SAMPLE_HTML.read_text(encoding="utf-8")

    text = extract_main_content(html, url="https://example.invalid/article")

    assert "# SYNTHETIC TEST DOCUMENT" in text
    assert "## Prepare a change" in text
    assert "This fictional database article contains exact words" in text
    assert "Keep this paragraph intact, including its important phrase." in text
    assert "Record the original setting." in text
    assert "Review the fictional option group." in text
    assert "Setting" in text and "Value" in text
    assert "mode" in text and "example-only" in text
    assert "Header noise" not in text
    assert "Navigation noise" not in text
    assert "Sidebar noise" not in text
    assert "Footer noise" not in text
    assert "Browser title noise" not in text


def test_fetch_continues_after_download_failure_and_empty_shell(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.yaml"
    sources_path.write_text(
        "- doc_id: synthetic-failed\n"
        "  url: https://example.invalid/failed\n"
        "- doc_id: synthetic-shell\n"
        "  url: https://example.invalid/shell\n"
        "- doc_id: synthetic-article\n"
        "  url: https://example.invalid/article\n",
        encoding="utf-8",
    )
    calls: list[str] = []
    html = SAMPLE_HTML.read_text(encoding="utf-8")

    def fake_fetch(url: str) -> str:
        calls.append(url)
        if url.endswith("/failed"):
            raise OSError("synthetic connection failure")
        if url.endswith("/shell"):
            return "<html><body><div id='app'></div><script>render()</script></body></html>"
        return html

    output_dir = tmp_path / "corpus"
    results = fetch_corpus(
        sources_path,
        output_dir,
        fetch=fake_fetch,
        retrieved_at=date(2026, 10, 9),
    )

    assert calls == [
        "https://example.invalid/failed",
        "https://example.invalid/shell",
        "https://example.invalid/article",
    ]
    assert [result.doc_id for result in results] == [
        "synthetic-failed",
        "synthetic-shell",
        "synthetic-article",
    ]
    assert [result.status for result in results] == ["error", "error", "ok"]
    assert "synthetic connection failure" in (results[0].error or "")
    assert "empty" in (results[1].error or "").lower()
    assert results[0].size == results[1].size == 0
    assert results[0].path is None and results[1].path is None
    assert not (output_dir / "synthetic-failed.md").exists()
    assert not (output_dir / "synthetic-shell.md").exists()

    extracted = extract_main_content(html, url="https://example.invalid/article")
    saved = (output_dir / "synthetic-article.md").read_text(encoding="utf-8")
    assert results[2].path == output_dir / "synthetic-article.md"
    assert results[2].size == len(extracted.encode("utf-8"))
    assert "doc_id: synthetic-article" in saved
    assert "url: https://example.invalid/article" in saved
    assert "retrieved_at: 2026-10-09" in saved
    assert f"sha256: {sha256(extracted.encode('utf-8')).hexdigest()}" in saved
    assert extracted in saved


def test_download_requests_html_from_documentation_sites(monkeypatch) -> None:
    sample = SAMPLE_HTML.read_bytes()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return sample

    def fake_urlopen(request, *, timeout):
        assert request.get_header("Accept") == "text/html"
        assert timeout > 0
        return Response()

    monkeypatch.setattr(corpus_fetch, "urlopen", fake_urlopen)
    assert corpus_fetch._download("https://example.invalid/article") == sample


def test_fetch_preserves_raw_markdown_article(tmp_path: Path) -> None:
    source = tmp_path / "sources.yaml"
    source.write_text(
        "- doc_id: synthetic-markdown\n"
        "  url: https://example.invalid/guide.markdown\n",
        encoding="utf-8",
    )
    article = (
        "# Synthetic Markdown Guide\n\n"
        "This is a fictional reference paragraph with more than twenty words, "
        "used only to verify that source Markdown survives the corpus fetcher "
        "without generated summaries or article text changes."
    )
    raw = "---\nsource: synthetic\n---\n\n" + article

    results = fetch_corpus(
        source, tmp_path / "output", fetch=lambda _url: raw,
        retrieved_at=date(2026, 10, 9),
    )

    assert results[0].status == "ok"
    saved = (tmp_path / "output" / "synthetic-markdown.md").read_text(encoding="utf-8")
    assert article in saved
    assert "source: synthetic" not in saved
