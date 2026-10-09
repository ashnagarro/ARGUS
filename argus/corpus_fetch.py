"""Deterministically fetch and extract public reference documents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, NavigableString, Tag


_SOURCE_ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_HEADING_TAGS = {f"h{level}" for level in range(1, 7)}
_BLOCK_TAGS = _HEADING_TAGS | {"p", "li", "table", "pre"}
_DROP_SELECTORS = (
    "script, style, noscript, nav, footer, header, aside, button, form, svg, "
    "[role='navigation'], [aria-hidden='true'], .awsdocs-page-header-container, "
    ".highlights, .toc, awsdocs-language-banner, awsdocs-copyright, "
    "awsdocs-thumb-feedback"
)


@dataclass(frozen=True, slots=True)
class Source:
    doc_id: str
    url: str


@dataclass(frozen=True, slots=True)
class FetchResult:
    doc_id: str
    url: str
    status: str
    size: int
    path: Path | None = None
    error: str | None = None


def load_sources(sources_path: Path) -> list[Source]:
    """Parse the intentionally small YAML list used by corpus/sources.yaml."""
    sources: list[Source] = []
    pending_id: str | None = None
    for line_number, line in enumerate(Path(sources_path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("- doc_id:"):
            if pending_id is not None:
                raise ValueError(f"{sources_path}:{line_number}: missing url for {pending_id}")
            pending_id = line.partition(":")[2].strip().strip('"\'')
            if not _SOURCE_ID.fullmatch(pending_id):
                raise ValueError(f"{sources_path}:{line_number}: invalid doc_id")
            continue
        if line.startswith("  url:") and pending_id is not None:
            url = line.partition(":")[2].strip().strip('"\'')
            if urlparse(url).scheme != "https" or not urlparse(url).netloc:
                raise ValueError(f"{sources_path}:{line_number}: url must be HTTPS")
            sources.append(Source(pending_id, url))
            pending_id = None
            continue
        raise ValueError(f"{sources_path}:{line_number}: unsupported source manifest line")
    if pending_id is not None:
        raise ValueError(f"{sources_path}: missing url for {pending_id}")
    ids = [source.doc_id for source in sources]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{sources_path}: duplicate doc_id")
    if not sources:
        raise ValueError(f"{sources_path}: no sources")
    return sources


def _inline_text(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text("", strip=False)).strip()


def _list_item_text(node: Tag) -> str:
    parts: list[str] = []
    for descendant in node.descendants:
        if isinstance(descendant, NavigableString) and descendant.find_parent("li") is node:
            parts.append(str(descendant))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _inside(node: Tag, names: set[str], root: Tag) -> bool:
    for parent in node.parents:
        if parent is root:
            break
        if isinstance(parent, Tag) and parent.name in names:
            return True
    return False


def _render_article(root: Tag) -> str:
    for unwanted in root.select(_DROP_SELECTORS):
        unwanted.decompose()
    for line_break in root.find_all("br"):
        line_break.replace_with("\n")

    blocks: list[str] = []
    for node in root.descendants:
        if not isinstance(node, Tag) or node.name not in _BLOCK_TAGS:
            continue
        if _inside(node, {"table", "pre"}, root):
            continue
        if node.name == "p" and _inside(node, {"li"}, root):
            continue
        if node.name in _HEADING_TAGS:
            text = _inline_text(node)
            if text:
                blocks.append(f"{'#' * int(node.name[1])} {text}")
        elif node.name == "p":
            text = _inline_text(node)
            if text:
                blocks.append(text)
        elif node.name == "li":
            text = _list_item_text(node)
            if text:
                blocks.append(f"- {text}")
        elif node.name == "table":
            rows: list[str] = []
            for row in node.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if cells:
                    rows.append(" | ".join(_inline_text(cell) for cell in cells))
            if rows:
                blocks.append("\n".join(rows))
        elif node.name == "pre":
            code = node.get_text("", strip=False).strip("\n")
            if code.strip():
                blocks.append("\n".join("    " + line for line in code.splitlines()))
    return "\n\n".join(blocks).strip()


def extract_main_content(html: str, *, url: str = "") -> str:
    """Extract article blocks from known server-rendered documentation layouts."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(url).hostname or ""
    heading: str | None = None
    if host == "docs.aws.amazon.com":
        root = soup.select_one("#main-col-body")
    elif host == "developer.hashicorp.com":
        root = soup.select_one(".mdx-content-container")
        title = soup.select_one("main#main h1")
        heading = _inline_text(title) if title else None
    else:
        root = soup.select_one("#main-col-body, article, main, [role='main']")
    if root is None:
        return ""
    text = _render_article(root)
    if heading and not text.startswith("# "):
        text = f"# {heading}\n\n{text}" if text else f"# {heading}"
    return text


def _extract_markdown(markdown: str) -> str:
    """Remove source metadata front matter while preserving the article body."""
    text = markdown.lstrip("\ufeff").replace("\r\n", "\n")
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if end is not None:
            text = "".join(lines[end + 1:])
    return text.strip()


def _download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ARGUS-corpus-fetch/1.0", "Accept": "text/html"})
    with urlopen(request, timeout=45) as response:
        return response.read()


def fetch_corpus(
    sources_path: Path,
    corpus_dir: Path,
    *,
    fetch: Callable[[str], bytes | str] | None = None,
    retrieved_at: date | str | None = None,
) -> list[FetchResult]:
    """Fetch each source independently; never generate or rewrite source prose."""
    sources = load_sources(Path(sources_path))
    output_dir = Path(corpus_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if retrieved_at is None:
        date_text = date.today().isoformat()
    elif isinstance(retrieved_at, date):
        date_text = retrieved_at.isoformat()
    else:
        date_text = date.fromisoformat(retrieved_at).isoformat()
    downloader = fetch or _download

    results: list[FetchResult] = []
    for source in sources:
        try:
            response = downloader(source.url)
            raw_text = response.decode("utf-8-sig") if isinstance(response, bytes) else response
            if urlparse(source.url).path.endswith((".markdown", ".md")):
                extracted = _extract_markdown(raw_text)
            else:
                extracted = extract_main_content(raw_text, url=source.url)
            if len(extracted.split()) < 20:
                raise ValueError("empty JavaScript shell or no usable article text")
            content_bytes = extracted.encode("utf-8")
            digest = sha256(content_bytes).hexdigest()
            destination = output_dir / f"{source.doc_id}.md"
            temporary = output_dir / f"{source.doc_id}.md.tmp"
            front_matter = (
                "---\n"
                f"doc_id: {source.doc_id}\n"
                f"url: {source.url}\n"
                f"retrieved_at: {date_text}\n"
                f"sha256: {digest}\n"
                "---\n\n"
            )
            temporary.write_text(front_matter + extracted + "\n", encoding="utf-8", newline="\n")
            temporary.replace(destination)
            results.append(FetchResult(source.doc_id, source.url, "ok", len(content_bytes), destination))
        except (OSError, UnicodeError, ValueError) as error:
            results.append(FetchResult(source.doc_id, source.url, "error", 0, error=str(error)))
    return results
