"""Grounded extraction: retrieve chunks → LLM extracts structure → deterministic logic.

This replaces hand-authored structured data. The LLM extracts the *structure* from
retrieved document chunks (generalises to any corpus, robust to PDF artifacts); precise
logic (ZIP membership, fee tiers) runs deterministically on the extracted records.
"""
