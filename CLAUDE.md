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
2. **No hand-authored business facts.** Prices, fees, ZIP coverage, hours, policies, etc.
   are **never** transcribed into code or config. Their single source of truth is the
   ingested documents. The only thing in code is *document-agnostic logic*.
3. **Deterministic plumbing, grounded facts.** Chunking, retrieval, schema validation,
   confirmation-gating, guardrails, and the mock store are deterministic code. *Facts* come
   from the documents at run time (RAG) and are validated into typed structures.
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

## Architecture
```
ANY documents
   │  parse (pdfplumber)         ← document-agnostic
   ▼
 chunks (structure-aware) ──► embed (bge-base, local) ──► hybrid index (BM25 + dense, RRF)
   │
   ▼  serving (all grounded in retrieved context; nothing hand-coded)
   ├─ Knowledge Q&A ............ RAG: LLM answers from retrieved chunks + citations
   └─ Structured actions ....... tool retrieves chunks → LLM extracts a pydantic-validated
        (eligibility, fees)       value (e.g. CoverageDecision) → deterministic confirm/commit
```
- **Orchestration:** LangGraph state machine — `safety → classify → retrieve → plan/act →
  validate → confirm (interrupt) → commit → respond`, with a `handoff` path. Confirm-before-commit
  is guaranteed by graph topology + a registry capability-split (mutating tools only in `commit`),
  cross-checked by a mutation ledger.
- **Booking API:** a FastAPI mock + in-process double sharing one service module (the simulated
  external system; deterministic, generic — it does not encode the docs' business facts).
- **Generalization contract:** the booking-critical structured values (coverage, fee quotes) are
  produced by **grounded extraction over retrieved chunks**, so they work on any service-area /
  pricing document, not just the provided ones.

## Repository layout
```
src/meridian/
  config.py            settings (env-overridable); clock.py (injected Clock; no datetime.now in logic)
  domain/              pure types: enums (mirror the API contract), value objects, errors
  ingestion/           parse (pdfplumber) → chunk → build index   [document-agnostic]
  retrieval/           embedder, bm25, hybrid (RRF), confidence/abstention, Retriever protocol
  extraction/          grounded structured extraction (LLM → pydantic) over retrieved chunks
  api_client/          typed Booking API client (HTTP) + in-process double
  tools/               LLM tool surface (READ_ONLY vs MUTATING) + pydantic arg schemas
  agent/               LangGraph state/nodes/graph/prompts/runner
  guardrails/          emergency (rules-first), scope, injection, fee-no-waive, limits
  tracing/             TurnTrace (the eval contract)
app/                   FastAPI mock Booking API + in-process double (generic simulated backend)
eval/                  datasets + harness (retrieval/answer/action metrics + generalization test)
data/
  corpus/              extracted markdown per doc (regenerable cache; committed for fast clone)
  index/               chunks + vectors + bm25 + manifest (regenerable cache)
files/                 the input PDFs (just the current sample; swappable)
tests/                 unit / api / tools / agent
```
> **Note:** `files/` holds the *current* sample only. The system treats it as "whatever corpus is
> present" — point it at any folder of PDFs and re-run `make ingest`.

## Commands
macOS/Linux use `make <target>`; Windows without make, run the underlying `python -m …` (see Makefile).
- `make install` — venv deps (Python 3.11; Ragas is an optional `[ragas]` extra)
- `make ingest` — parse → chunk → embed → index for whatever is in `files/`
- `make cli` / `make demo-web` — talk to the assistant (CLI; minimal static web demo)
- `make api` — run the mock Booking API
- `make test` / `make lint` / `make typecheck` — the gate
- `make eval` — deterministic eval tier (keyless, CI gate); `make eval-judged` adds the LLM judge

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
1. Put PDFs in `files/` (or repoint `MERIDIAN_FILES_DIR`). 2. `make ingest`. 3. Done — no code
changes. New service-area or pricing docs are handled by the same grounded-extraction path. Add an
eval case if you want to assert a specific new fact.

## Status (kept honest)
- ✅ Scaffold, deterministic plumbing, mock Booking API + fee logic, eval-able core, 56 tests green.
- 🔁 **Pivoting** the data layer from hand-authored YAML to **grounded extraction from the documents**
  (per the principles above) so it generalizes to arbitrary corpora.
- ⏭️ Then: retrieval, the grounded-extraction tools, the LangGraph agent, CLI, eval (incl. the
  generalization test), minimal web demo, docs.
