"""Chunk the committed markdown corpus into retrievable, citable units.

**Structure-aware, but document-agnostic.** Chunks are split by the ``##`` section
headings the extractor derived from font size — so a whole pricing table, a full
Gold-vs-Platinum comparison, an emergency-trigger list, or a single FAQ Q&A becomes one
coherent chunk (never split mid-unit). Over-long sections are windowed at line boundaries
with overlap, and documents with *no* detectable headings fall back to a plain sliding
window — so it still works on any corpus. Each chunk carries citation metadata.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from ..config import get_settings

DEFAULT_TARGET_CHARS = 700
DEFAULT_OVERLAP_LINES = 1
_SECTION_RE = re.compile(r"^##\s+(.*)$")
_INTRO = "(intro)"


class Chunk(BaseModel):
    """A retrievable, citable slice of a source document."""

    chunk_id: str
    doc_id: str
    title: str
    version: str
    source: str
    section: str
    ordinal: int
    text: str
    char_start: int
    char_end: int

    def citation(self) -> str:
        """Human-readable citation token, e.g. ``[hvac_pricing v3.0 §Repair Tiers]``."""
        ver = f" v{self.version}" if self.version else ""
        sec = f" §{self.section}" if self.section and self.section != _INTRO else ""
        return f"[{self.doc_id}{ver}{sec}]"


def parse_doc(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a corpus markdown file into (front-matter, body) with the H1 line dropped."""
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = raw
    if raw.startswith("---"):
        _, front, body = raw.split("---", 2)
        meta = yaml.safe_load(front) or {}
    lines = body.strip().split("\n")
    if lines and lines[0].startswith("# "):  # drop the redundant H1 (title is in front-matter)
        lines = lines[1:]
    return meta, "\n".join(lines).strip()


def _line_offsets(lines: list[str]) -> list[int]:
    """Return the character offset of each line within the joined body."""
    offsets, pos = [], 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1
    return offsets


def chunk_document(
    meta: dict[str, Any],
    body: str,
    target_chars: int = DEFAULT_TARGET_CHARS,
    overlap_lines: int = DEFAULT_OVERLAP_LINES,
) -> list[Chunk]:
    """Split one document's body into structure-aware, citable chunks."""
    doc_id = str(meta.get("doc_id", "unknown"))
    title = str(meta.get("title", doc_id))
    version = str(meta.get("version", ""))
    source = str(meta.get("source", ""))
    lines = body.split("\n")
    offsets = _line_offsets(lines)

    def make(section: str, idxs: list[int], ordinal: int) -> Chunk | None:
        content = [lines[k] for k in idxs if lines[k].strip()]
        if not content:
            return None
        body_text = "\n".join(content).strip()
        header = f"{title} — {section}" if section != _INTRO else title
        return Chunk(
            chunk_id=f"{doc_id}#{ordinal}",
            doc_id=doc_id,
            title=title,
            version=version,
            source=source,
            section=section,
            ordinal=ordinal,
            text=f"{header}\n{body_text}" if header else body_text,
            char_start=offsets[idxs[0]],
            char_end=offsets[idxs[-1]] + len(lines[idxs[-1]]),
        )

    sections = _split_sections(lines)
    if sections is None:  # no headings detected -> generic sliding-window fallback
        sections = [
            (_INTRO, win)
            for win in _windows(list(range(len(lines))), lines, target_chars, overlap_lines)
        ]
    else:
        sections = [
            (heading, win)
            for heading, idxs in sections
            for win in _windows(idxs, lines, target_chars, overlap_lines)
        ]

    chunks: list[Chunk] = []
    for heading, idxs in sections:
        chunk = make(heading, idxs, len(chunks))
        if chunk is not None:
            chunks.append(chunk)
    return chunks


def _split_sections(lines: list[str]) -> list[tuple[str, list[int]]] | None:
    """Split line indices into (heading, content-indices). None if no headings exist."""
    if not any(_SECTION_RE.match(line) for line in lines):
        return None
    sections: list[tuple[str, list[int]]] = []
    heading: str = _INTRO
    idxs: list[int] = []
    for i, line in enumerate(lines):
        match = _SECTION_RE.match(line)
        if match:
            if idxs:
                sections.append((heading, idxs))
            heading, idxs = match.group(1).strip(), []
        else:
            idxs.append(i)
    if idxs:
        sections.append((heading, idxs))
    return sections


def _windows(idxs: list[int], lines: list[str], target: int, overlap: int) -> list[list[int]]:
    """Window a list of line indices so each window stays under ``target`` chars."""
    if sum(len(lines[k]) for k in idxs) <= target:
        return [idxs] if idxs else []
    out: list[list[int]] = []
    window: list[int] = []
    for i in idxs:
        if window and sum(len(lines[k]) for k in window) + len(lines[i]) > target:
            out.append(window)
            window = window[-overlap:] if overlap else []
        window.append(i)
    if window:
        out.append(window)
    return out


def chunk_corpus(
    target_chars: int = DEFAULT_TARGET_CHARS, overlap_lines: int = DEFAULT_OVERLAP_LINES
) -> list[Chunk]:
    """Chunk every ``data/corpus/*.md`` document into a flat list of chunks."""
    chunks: list[Chunk] = []
    for path in sorted(get_settings().corpus_dir.glob("*.md")):
        meta, body = parse_doc(path)
        chunks.extend(chunk_document(meta, body, target_chars, overlap_lines))
    return chunks


def main() -> None:
    """Dev tool: chunk the corpus and print a per-doc summary + section list."""
    chunks = chunk_corpus()
    by_doc: dict[str, list[str]] = {}
    for c in chunks:
        by_doc.setdefault(c.doc_id, []).append(c.section)
    print(f"total chunks: {len(chunks)}")  # noqa: T201
    for doc_id, sections in sorted(by_doc.items()):
        print(f"  {doc_id} ({len(sections)}): {sections}")  # noqa: T201


if __name__ == "__main__":
    main()
