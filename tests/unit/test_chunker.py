"""Unit tests for structure-aware chunking (no index/model needed)."""

from __future__ import annotations

from meridian.ingestion.chunker import chunk_corpus


def test_chunks_have_metadata_and_unique_ids() -> None:
    chunks = chunk_corpus()
    assert len(chunks) > 30  # section-aware split, not a handful of giant chunks
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert c.doc_id and c.title and c.text
        assert c.char_end > c.char_start


def test_plan_table_stays_one_chunk_for_comparison() -> None:
    chunks = chunk_corpus()
    plans = [c for c in chunks if c.doc_id == "hvac_pricing" and c.section == "Maintenance Plans"]
    assert len(plans) == 1
    text = plans[0].text
    assert "Silver" in text and "Gold" in text and "Platinum" in text


def test_coverage_table_stays_one_chunk() -> None:
    chunks = chunk_corpus()
    cov = [
        c for c in chunks if c.doc_id == "service_area_north" and c.section == "Covered ZIP Codes"
    ]
    assert len(cov) == 1
    text = cov[0].text
    for county in ("Fairfax", "Arlington", "Alexandria", "Loudoun"):
        assert county in text


def test_faq_questions_become_separate_chunks() -> None:
    chunks = chunk_corpus()
    faq_sections = [c.section for c in chunks if c.doc_id == "faq_booking"]
    assert len(faq_sections) >= 5
    assert any("advance" in s.lower() for s in faq_sections)  # "How far in advance can I book?"


def test_citation_token_includes_section() -> None:
    chunks = chunk_corpus()
    chunk = next(
        c for c in chunks if c.doc_id == "hvac_pricing" and c.section == "Maintenance Plans"
    )
    assert chunk.citation() == "[hvac_pricing v3.0 §Maintenance Plans]"
