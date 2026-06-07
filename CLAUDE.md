# CLAUDE.md — Engineering Guide for the Meridian Assistant

Guidance for any engineer (or Claude Code) working in this repo. Read this first.

## What this is
A document-grounded AI contact-center assistant for a home-services company. It answers
policy/FAQ questions with citations, runs an agentic booking flow (check service-area
eligibility → create/reschedule via a mock API, with confirm-before-commit), and hands off
to a human when unsure / out of scope / missing info. Ships with an evaluation harness.

## The non-negotiable design principles
These are what the design is judged on — **sustainability, reproducibility, generalization**.

1. **Document-agnostic.** The system must work on an *arbitrary* corpus. Dropping 1,000 new
   PDFs in and re-running ingestion must work with **zero code changes**. Nothing may be
   special-cased to the current 13 documents.
2. **No hand-authored business facts. Schema is the API; data is compiled from docs.**
   We hand-define only the small, finite set of *capability schemas* (the SHAPE of a fact a
   capability needs — a fee has tiers, coverage has ZIP ranges) — determined by what the
   assistant *does*, not by the corpus, so it never grows with document count. Every *value*
   (prices, fees, ZIP coverage, hours) is **compiled from the documents** by an LLM extractor
   into validated records under `data/extracted/`. Never transcribe a value into code or YAML.
   The *one* exception is the Booking API **contract** (window bands, max-advance, notes length
   from doc 12, which we *implement*) + a documented federal-holiday stub — these live in
   `api_contract.py` with explicit provenance and do not change as the corpus grows.
3. **Deterministic plumbing, grounded facts; compile-time extraction, runtime determinism.**
   Chunking, retrieval, schema validation, confirmation-gating, guardrails, ZIP-membership, and
   fee math are deterministic code. *Facts* are extracted from documents **at compile time**
   (`make extract` → `data/extracted/*.json`, cached/committed); at **runtime** the assistant and
   the mock API load those records and apply deterministic logic — **no LLM/retrieval in the
   booking-critical path**, so a retrieval glitch can never change who we book or what we charge.
   Open-ended knowledge Q&A is answered by RAG over retrieved chunks with citations.
4. **Everything is traceable.** Every answer cites the chunk(s) it used; every extracted
   structured value carries its source + a confidence. No fact is presented as documented
   truth unless it is grounded.
5. **Reproducible.** The pipeline is code; artifacts (index, caches) are regenerable from any
   corpus. LLM calls run at temperature 0 and are cached (record/replay) so results reproduce
   offline.
6. **Confidence-aware.** Low retrieval/extraction confidence → abstain and hand off to a
   human (the real-world control: a review queue), never guess.
7. **Eval-driven, including generalization.** We measure retrieval, answer, and action
   correctness *and* prove the pipeline handles unseen documents (a held-out / synthetic-doc
   test), not just accuracy on the sample.

## Architecture — a two-phase knowledge-compilation pipeline
```
COMPILE TIME (offline; needs key for a cold cache; reproducible; `make ingest` + `make extract`)
  ANY documents ─ parse (pdfplumber) ─► structure-aware chunks ─► embed (bge-base) ─► hybrid index
                                                   │
                                                   └─► grounded extractors (parent-doc retrieval →
                                                       LLM → validated record) ─► data/extracted/*.json
                                                       (coverage, fees, branch hours) + manifest

RUNTIME (keyless; deterministic)
  ├─ Open-ended knowledge Q&A .... RAG: LLM answers from retrieved chunks + citations
  └─ Booking-critical facts ...... load data/extracted/*.json → deterministic logic
       (eligibility, fees, hours)   (ZIP-range membership, fee tiers) — no LLM/retrieval here
```
- **Schema vs data:** a handful of capability schemas (`extraction/schemas.py`) are hand-defined;
  all values are compiled from docs. Per-entity facts (e.g. per-service-line diagnostic fees) are
  compiled by iterating the known entities with a targeted retrieval each, so completeness does
  not depend on every relevant doc ranking in one top-N — this is what scales to many documents.
- **Orchestration:** LangGraph state machine — `safety → classify → retrieve → plan/act →
  validate → confirm (interrupt) → commit → respond`, with a `handoff` path. Confirm-before-commit
  is guaranteed by graph topology + a registry capability-split (mutating tools only in `commit`),
  cross-checked by a mutation ledger.
- **Booking API:** a FastAPI mock + in-process double sharing one service module; it reads the same
  compiled `data/extracted/fees.json` (no hand-authored fee constants) and the doc-12 contract.
- **Generalization:** proven by `tests/unit/test_generalization.py` — a synthetic unseen document
  compiles correctly through the *unchanged* extractor (new counties, glyph artifacts, gaps).

## Repository layout
```
src/meridian/
  config.py            settings (env-overridable); clock.py (injected Clock; no datetime.now in logic)
  api_contract.py      Booking API contract constants (doc 12) + federal-holiday stub — NOT facts
  domain/              pure types: enums (mirror the API contract), value objects, errors
  ingestion/           parse (pdfplumber) → chunk → build index   [document-agnostic]
  retrieval/           embedder, bm25, hybrid (RRF), confidence/abstention, swappable VectorStore protocol
  llm/                 Anthropic structured-output client + on-disk response cache (record/replay)
  extraction/          COMPILE-TIME: schemas (capability shapes), extractors (grounded), compile.py
  knowledge/           RUNTIME: loader (reads data/extracted) + coverage/fees/branches (det. logic)
  api_client/          typed Booking API client (HTTP) + in-process double
  tools/               LLM tool surface (READ_ONLY vs MUTATING) + pydantic arg schemas
  agent/               LangGraph state/nodes/graph/prompts/runner
  guardrails/          emergency (rules-first), scope, injection, fee-no-waive, limits
  tracing/             TurnTrace (the eval contract)
  cli.py               composition root + interactive REPL + scripted demo driver
app/                   FastAPI mock Booking API + in-process double (reads data/extracted/fees.json)
server/                minimal web-demo server (FastAPI shell reusing the runner; optional)
web/                   static demo page: index.html + app.js + style.css (vanilla JS, no build step)
eval/                  datasets + harness (retrieval/answer/action metrics + generalization test)
data/
  corpus/              extracted markdown per doc (regenerable cache; committed for fast clone)
  index/               chunks + vectors + bm25 + manifest (regenerable cache)
  extracted/           COMPILED facts: coverage.json, fees.json, branches.json + provenance manifest
  llm_cache/           cached LLM extraction responses (committed → keyless, reproducible replay)
files/                 the input PDFs (just the current sample; swappable)
tests/                 unit / api / tools / agent
```
> **Note:** `files/` holds the *current* sample only. The system treats it as "whatever corpus is
> present" — point it at any folder of PDFs and re-run `make ingest`.

## Commands
macOS/Linux use `make <target>`; Windows without make, run the underlying `python -m …` (see Makefile).
- `make install` — venv deps (Python 3.11; Ragas is an optional `[ragas]` extra)
- `make ingest` — parse → chunk → embed → index for whatever is in `files/`
- `make extract` — compile booking-critical facts from the corpus → `data/extracted/` (keyless if the LLM cache is present)
- `make cli` / `make demo-web` — talk to the assistant (CLI; minimal static web demo)
- `make api` — run the mock Booking API
- `make test` / `make lint` / `make typecheck` — the gate
- `make eval` — deterministic eval tier (keyless, CI gate); `make eval-judged` is reserved for a
  judged tier (LLM groundedness judge + optional Ragas) that is **scaffolded, not yet implemented**

## Conventions
- **Python 3.11**, `src/` layout, pinned deps + committed lockfile.
- **ruff + mypy + pytest** must be green (the gate). Google-style docstrings, full type hints, PEP 8.
- **No `datetime.now()` in business logic** — inject the `Clock`; a CI grep enforces this.
- **No hardcoded business facts** — if you're about to type a price/fee/ZIP/hour into code or YAML,
  stop: it belongs in a document, retrieved at run time.
- **Structured outputs** for any LLM-produced value used by code (pydantic-validated).
- **Determinism:** temp 0, frozen clock in tests/eval, deterministic tie-breaks; cache LLM calls.

## Determinism & reproducibility
- Two eval tiers: a **deterministic tier** (no LLM in the correctness path; keyless; the CI gate)
  and a **judged tier** (LLM-graded; cached/record-replay so numbers reproduce offline).
- Indexes/corpus are regenerable caches; a manifest records the embed-model + corpus hash.

## How to extend / add documents
1. Put PDFs in `files/` (or repoint `MERIDIAN_FILES_DIR`). 2. `make ingest`. 3. `make extract`.
4. Done — no code changes. New service-area / pricing / hours docs are handled by the same
grounded-extraction path; per-entity facts iterate the known entities. Add an eval case if you want
to assert a specific new fact. Add a *new kind* of capability = register one extractor (schema +
query) in `extraction/` and a loader in `knowledge/` — still zero hand-authored data.

## Status (kept honest)
- ✅ Scaffold, deterministic plumbing, mock Booking API (reads compiled fees), eval-able core.
- ✅ Document-agnostic ingestion + structure-aware chunking + hybrid retrieval (RRF) + abstention.
- ✅ **Knowledge-compilation pipeline**: LLM client (cached), grounded extractors, `make extract`
  → `data/extracted/*.json`; runtime loads compiled records + deterministic logic. **All
  hand-authored YAML removed.**
- ✅ Tools + typed API client (P4); LangGraph agent w/ confirm-before-commit by topology (P5);
  CLI + scripted demo (P6).
- ✅ **Eval harness (P7)**: categorical safety invariants (emergency recall, confirmation-gating)
  proven against the mutation ledger + deterministic correctness + retrieval metrics, run as a CI
  gate that **fails** (not skips) when its committed inputs are missing. Hardened after an
  adversarial self-review (12 confirmed findings fixed).
- ✅ **Minimal web demo (P8)**: `server/` (FastAPI shell reusing the runner) + `web/` (vanilla JS,
  no build step) — citation chips, confirm modal, trace panel; output rendered as text (XSS-safe).
- ✅ **Docs (P9)**: README (run / design / left-out / debugging methodology), path-to-production,
  results summary (`eval/results.md`), ASSUMPTIONS + guardrails, DESIGN_EVOLUTION.
- Current: **149 tests green**; ruff + mypy clean; eval 16/16, emergency 0/3, gating 0/8,
  recall@5 100%/MRR 1.00; keyless replay verified end-to-end (eval + full suite pass with no key).
