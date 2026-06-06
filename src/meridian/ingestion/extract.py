"""Extract the knowledge-pack PDFs into committed, structured markdown.

Run once (``python -m meridian.ingestion.extract``). The markdown under ``data/corpus/``
is the canonical, regenerable source the chunker builds on, so a parser glitch can't
silently corrupt retrieval or citations.

Document-agnostic structure recovery: section headings are derived from **font size**
(relative to the body's most-common size — works on any well-formatted PDF), plus a "ends
with ?" rule for FAQ-style questions. Good row-grouping comes from ``layout=False`` text;
heading lines are matched back by text and marked as ``##`` so the chunker can split by
section. Repeating header/footer chrome is stripped by pattern; the title is de-duplicated.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pdfplumber

from ..config import get_settings

_FOOTER_RE = re.compile(
    r"Version\s+v?(?P<version>[\d.]+)\s*[·.]\s*Updated\s+(?P<updated>\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_PAGE_RE = re.compile(r"^\s*Page\s+\d+\s*$", re.IGNORECASE)
_INTERNAL_RE = re.compile(r"INTERNAL USE ONLY", re.IGNORECASE)
_CID_RE = re.compile(r"\(cid:\d+\)")  # unmapped-glyph artifacts (bullets) — safe to drop
_HEADER = "Meridian Home Services"
_CATEGORY_TAGS = {
    "SERVICE AREA",
    "PRICING",
    "POLICY",
    "WARRANTY",
    "FAQ",
    "REFERENCE",
    "BRANCH INFO",
    "API SPEC",
    "TEST DATA",
}
_EXCLUDED = {"12_booking_api_spec", "13_customer_messages"}

_TITLE_MARGIN = 5.0  # a title is >= body_size + this many points
_HEADING_MARGIN = 1.5  # a section heading is >= body_size + this many points


@dataclass
class ExtractedDoc:
    """A doc extracted from a PDF, ready to write as markdown."""

    doc_id: str
    title: str
    version: str
    updated: str
    source: str
    body: str


def _doc_id(stem: str) -> str:
    """Map a filename stem like ``03_hvac_pricing`` to doc_id ``hvac_pricing``."""
    return re.sub(r"^\d+_", "", stem)


def _norm(text: str) -> str:
    """Normalise whitespace + case for matching heading text across passes."""
    return re.sub(r"\s+", " ", text).strip().lower()


def _is_chrome(line: str) -> bool:
    """True if ``line`` is repeating header/footer chrome (brand, tag, version, page)."""
    s = line.strip()
    if not s:
        return False
    if _HEADER in s or s in _CATEGORY_TAGS:
        return True
    return bool(_PAGE_RE.match(s) or _INTERNAL_RE.search(s) or _FOOTER_RE.search(s))


def _line_sizes(page: pdfplumber.page.Page) -> list[tuple[str, float]]:
    """Reconstruct visual lines as ``(text, max_font_size)`` from words."""
    by_top: dict[int, list[dict[str, Any]]] = {}
    for word in page.extract_words(extra_attrs=["size"]):
        by_top.setdefault(round(float(word["top"])), []).append(word)
    lines: list[tuple[str, float]] = []
    for top in sorted(by_top):
        words = sorted(by_top[top], key=lambda w: w["x0"])
        text = _CID_RE.sub("", " ".join(w["text"] for w in words)).strip()
        if text:
            size = max(float(w.get("size", 0.0)) for w in words)
            lines.append((text, size))
    return lines


def _classify(line_sizes: list[tuple[str, float]]) -> tuple[str, set[str]]:
    """Return (title_text, set of normalised heading texts) from font sizes."""
    content = [(t, s) for t, s in line_sizes if not _is_chrome(t)]
    if not content:
        return "", set()
    body_size = Counter(round(s) for _, s in content).most_common(1)[0][0]
    max_size = max(s for _, s in content)
    title = ""
    headings: set[str] = set()
    for text, size in content:
        if size == max_size and size >= body_size + _TITLE_MARGIN:
            title = text
        elif size >= body_size + _HEADING_MARGIN:
            headings.add(_norm(text))
        elif text.rstrip().endswith("?") and size >= body_size:
            headings.add(_norm(text))  # FAQ-style question
    return title, headings


def extract_pdf(path: Path) -> ExtractedDoc:
    """Extract one PDF into structured markdown (title + ``##`` sections + body)."""
    version = updated = ""
    text_lines: list[str] = []
    line_sizes: list[tuple[str, float]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=False) or ""
            for match in _FOOTER_RE.finditer(text):
                version, updated = match.group("version"), match.group("updated")
            text_lines.extend(_CID_RE.sub("", line).strip() for line in text.split("\n"))
            line_sizes.extend(_line_sizes(page))

    title, headings = _classify(line_sizes)
    title_norm = _norm(title)

    body: list[str] = []
    blank = False
    for line in text_lines:
        if not line:
            if body and not blank:
                body.append("")
            blank = True
            continue
        if _is_chrome(line):
            continue
        blank = False
        norm = _norm(line)
        if title and norm == title_norm:  # title lives in front-matter + the H1 (drop dupes)
            continue
        body.append(f"## {line}" if norm in headings else line)

    return ExtractedDoc(
        doc_id=_doc_id(path.stem),
        title=title,
        version=version,
        updated=updated,
        source=path.name,
        body="\n".join(body).strip() + "\n",
    )


def to_markdown(doc: ExtractedDoc) -> str:
    """Render an :class:`ExtractedDoc` as front-matter + a titled, sectioned body."""
    return (
        f"---\n"
        f"doc_id: {doc.doc_id}\n"
        f"title: {doc.title}\n"
        f"version: {doc.version}\n"
        f"updated: {doc.updated}\n"
        f"source: {doc.source}\n"
        f"---\n\n"
        f"# {doc.title}\n\n"
        f"{doc.body}"
    )


def corpus_pdf_paths() -> list[Path]:
    """Return the knowledge-pack PDF paths included in the RAG corpus (sorted)."""
    files_dir = get_settings().files_dir
    return sorted(p for p in files_dir.glob("*.pdf") if p.stem not in _EXCLUDED)


def extract_corpus() -> list[Path]:
    """Extract all corpus PDFs to ``data/corpus/*.md`` and return the written paths."""
    out_dir = get_settings().corpus_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for pdf_path in corpus_pdf_paths():
        doc = extract_pdf(pdf_path)
        (out_dir / f"{doc.doc_id}.md").write_text(to_markdown(doc), encoding="utf-8")
        written.append(out_dir / f"{doc.doc_id}.md")
    return written


def main() -> None:
    """CLI entry point: extract the corpus and report what was written."""
    for path in extract_corpus():
        print(f"wrote {path}")  # noqa: T201 - script output


if __name__ == "__main__":
    main()
