"""Load and search the local Markdown reference library."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import log
from pathlib import Path
import re
from typing import Mapping


_FRONT_MATTER_DELIMITER = "---"
_REQUIRED_FIELDS = ("doc_id", "url", "retrieved_at")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_WORD = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True)
class Section:
    doc_id: str
    number: int
    heading: str
    text: str


@dataclass(frozen=True)
class Document:
    doc_id: str
    url: str
    retrieved_at: str
    body: str
    sections: tuple[Section, ...]


def _parse_front_matter(path: Path, content: str) -> tuple[dict[str, str], str]:
    lines = content.lstrip("\ufeff").splitlines(keepends=True)
    if not lines or lines[0].strip() != _FRONT_MATTER_DELIMITER:
        raise ValueError(f"{path.name}: missing Markdown front matter")

    end = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == _FRONT_MATTER_DELIMITER),
        None,
    )
    if end is None:
        raise ValueError(f"{path.name}: front matter is not closed")

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            raise ValueError(f"{path.name}: invalid front matter line")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key in fields:
            raise ValueError(f"{path.name}: duplicate front matter field {key}")
        fields[key] = value

    missing = [key for key in _REQUIRED_FIELDS if not fields.get(key)]
    if missing:
        raise ValueError(f"{path.name}: missing front matter field(s): {', '.join(missing)}")
    return fields, "".join(lines[end + 1 :]).strip()


def _split_sections(doc_id: str, body: str) -> tuple[Section, ...]:
    sections: list[Section] = []
    heading = "Introduction"
    content: list[str] = []

    def finish() -> None:
        text = "\n".join(content).strip()
        if text:
            sections.append(Section(doc_id, len(sections) + 1, heading, text))

    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            finish()
            heading = match.group(1).strip()
            content = []
        else:
            content.append(line)
    finish()

    if not sections:
        sections.append(Section(doc_id, 1, heading, ""))
    return tuple(sections)


def load_corpus(corpus_dir: Path) -> dict[str, Document]:
    """Read Markdown files with doc_id, url and retrieved_at front matter."""
    documents: dict[str, Document] = {}
    for path in sorted(corpus_dir.glob("*.md")):
        fields, body = _parse_front_matter(path, path.read_text(encoding="utf-8"))
        doc_id = fields["doc_id"]
        if doc_id in documents:
            raise ValueError(f"{path.name}: duplicate doc_id {doc_id}")
        documents[doc_id] = Document(
            doc_id=doc_id,
            url=fields["url"],
            retrieved_at=fields["retrieved_at"],
            body=body,
            sections=_split_sections(doc_id, body),
        )
    return documents


def read_section(doc_id: str, number: int, documents: Mapping[str, Document]) -> Section:
    """Return a numbered section (numbers start at one)."""
    document = documents[doc_id]
    if number < 1 or number > len(document.sections):
        raise KeyError(f"Section {number} does not exist in {doc_id}")
    return document.sections[number - 1]


def _terms(text: str) -> Counter[str]:
    return Counter(_WORD.findall(text.lower()))


def search_corpus(
    query: str, documents: Mapping[str, Document], limit: int = 5
) -> list[Section]:
    """Rank matching sections with term rarity and section-length normalization."""
    if limit <= 0:
        return []
    query_terms = set(_terms(query))
    if not query_terms:
        return []

    sections = [section for document in documents.values() for section in document.sections]
    if not sections:
        return []
    term_counts = [_terms(f"{section.heading} {section.text}") for section in sections]
    heading_counts = [_terms(section.heading) for section in sections]
    lengths = [sum(counts.values()) for counts in term_counts]
    average_length = sum(lengths) / len(lengths) or 1.0
    document_frequency = {
        term: sum(term in counts for counts in term_counts) for term in query_terms
    }

    matches: list[tuple[float, Section]] = []
    for section, counts, title_counts, length in zip(
        sections, term_counts, heading_counts, lengths
    ):
        score = 0.0
        for term in query_terms:
            frequency = counts[term] + 2 * title_counts[term]
            if not frequency:
                continue
            inverse_frequency = log(
                1 + (len(sections) - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            score += inverse_frequency * frequency * 2.2 / (
                frequency + 1.2 * (0.25 + 0.75 * length / average_length)
            )
        if score:
            matches.append((score, section))

    matches.sort(key=lambda item: (-item[0], item[1].doc_id, item[1].number))
    return [section for _, section in matches[:limit]]
