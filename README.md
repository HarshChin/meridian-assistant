# Meridian Home Services — AI Contact-Center Assistant

A document-grounded AI contact-center assistant for a mid-market home-services company
(HVAC / plumbing / electrical). It:

1. **Answers** policy/FAQ questions **grounded in the provided knowledge pack, with citations** and
   full traceability;
2. Runs an **agentic flow** — checks ZIP **service-area eligibility**, then **creates / reschedules /
   cancels a booking** via a mock Booking API, with input validation and a **confirm-before-commit**
   step;
3. **Hands off to a human** when confidence is low, the request is out of scope, missing info, or an
   **emergency**;
4. Ships an **evaluation harness** measuring retrieval quality and answer/action correctness, with
   **categorical safety invariants** as a CI gate.

The design is judged on three things and built around them: **sustainability** (works on an
arbitrary corpus, not just the sample), **reproducibility** (keyless, deterministic replay), and
**generalization** (proven on an unseen synthetic question).

> **▶ To run it, start with [`RUNBOOK.md`](./RUNBOOK.md)** — a copy-paste playbook for the web UI,
> CLI, eval, Swagger/mock API, and tests, with keyless sample questions to try.
>
> Companion docs: [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) (data conflicts + decisions + guardrails),
> [`DESIGN_EVOLUTION.md`](./DESIGN_EVOLUTION.md) (what we tried, what broke, how we changed it),
> [`docs/path_to_production.md`](./docs/path_to_production.md),
> [`docs/architecture.html`](./docs/architecture.html) (visual workflow), and the generated
> [`eval/results.md`](./eval/results.md).

---

## The one idea that matters: schema is the API, data is compiled from the documents

The hard requirement was **no hand-authored business facts** — the system must work if you drop
1,000 new PDFs in and re-run ingestion, with **zero code changes**. So nothing is special-cased to
the current 13 documents.

We hand-define only a small, finite set of **capability schemas** — the *shape* of a fact a
capability needs (a fee has tiers; coverage has ZIP ranges) — determined by what the assistant
*does*, not by the corpus, so it never grows with document count. Every **value** (prices, fees, ZIP
coverage, hours) is **compiled from the documents** by an LLM extractor into validated, cited records
under `data/extracted/`. At runtime the booking-critical path loads those records and applies
**deterministic** logic — **no LLM or retrieval in the booking-critical path**, so a retrieval glitch
can never change who we book or what we charge.

```
COMPILE TIME (offline; needs a key only for a cold cache; reproducible)
  ANY documents ─ parse (pdfplumber) ─► structure-aware chunks ─► embed (bge-base) ─► hybrid index
                                                  │
                                                  └─► grounded extractors (parent-doc retrieval →
                                                      LLM → validated record) ─► data/extracted/*.json
                                                      (coverage, fees, branch hours) + provenance

RUNTIME (keyless; deterministic)
  ├─ Open-ended knowledge Q&A ... RAG: LLM answers from retrieved chunks + citations
  └─ Booking-critical facts ..... load data/extracted/*.json → deterministic logic
       (eligibility, fees, hours)  (ZIP-range membership, fee tiers) — no LLM / retrieval here
```

---

## Quickstart

Requires **Python 3.11** and git. Every `make` target wraps one `python -m …` command, so on
Windows without `make` you can run the underlying command directly (see the `Makefile`).

```bash
# 1) create + activate a virtual environment
py -3.11 -m venv .venv            # Windows:   .venv\Scripts\Activate.ps1
# python3.11 -m venv .venv        # macOS/Linux: source .venv/bin/activate

# 2) install (core + dev tools; Ragas is an OPTIONAL extra, never required)
make install                      # or: python -m pip install -e ".[dev]"

# 3) the retrieval index + compiled facts + LLM cache are COMMITTED, so you can skip straight to
#    running. To regenerate from scratch (needs a key for a cold cache):
#    make ingest    # parse → chunk → embed → index   (document-agnostic)
#    make extract   # compile booking-critical facts → data/extracted/

# 4) talk to the assistant
make cli                          # interactive REPL
make demo                         # scripted, deterministic replay of a curated transcript
```

**API key.** The **deterministic eval tier and the whole test suite run without a key** — the
agent's temperature-0 LLM calls replay from a committed cache. Only the **live** agent (`make cli`,
`make demo-web`) needs `ANTHROPIC_API_KEY` for messages not already in the cache (copy
`.env.example` → `.env`). A judged eval tier (LLM groundedness judge + optional Ragas) is
*scaffolded but not yet implemented* — `make eval-judged` currently runs the deterministic tier.

### Try it

| Command | What you get |
|---|---|
| `make cli` | Interactive assistant. Ask a policy question (cited answer), book/reschedule (confirm-before-commit), trigger an emergency (instant handoff). |
| `make demo` | Deterministic scripted run spanning knowledge, emergency, booking, and status (`--trace` shows the decision trace). |
| `make demo-web` | Minimal static web demo at `http://localhost:8800` — chat, **citation chips**, a **confirm modal**, and a per-turn **trace** panel. The suggested prompts replay keyless. |
| `make api` | The mock Booking API (doc-12 contract) over HTTP. |
| `make eval` | The deterministic eval tier (keyless CI gate) → regenerates `eval/results.md`. |
| `make test` / `make check` | Test suite / full gate (lint + types + tests). |

---

## The four capabilities → where they live

| Capability | Where |
|---|---|
| 1. Grounded answers + citations / traceability | `ingestion/` + `retrieval/` (hybrid RRF) → agent `retrieve`/`answer` nodes; every answer carries inline `[source: …]` citations recorded in `TurnTrace`. |
| 2. Agentic ZIP → create / reschedule / cancel + validation + confirm | `tools/` (read-only vs mutating split) → agent `plan_booking` → `confirm` (interrupt) → `commit`; pydantic-validated args; `app/` mock Booking API. |
| 3. Safe fallback / human handoff | `guardrails/` (rules-first emergency union, scope, injection) + retrieval abstention + the agent `handoff` path with the 24/7 line. |
| 4. Eval harness | `eval/` — categorical safety invariants + deterministic correctness + retrieval metrics, run as a CI gate. |

---

## Architecture

**Orchestration** is a LangGraph state machine:
`safety → classify → (retrieve | lookup | plan_booking | handoff) → … → confirm (interrupt) →
commit → respond`. **Confirm-before-commit is guaranteed by the graph topology** (the `commit` node
is reachable only after an approved `confirm`) **plus** a capability split (mutating tools only run in
`commit`), **plus** a per-turn approval assertion, **cross-checked** by the mock API's independent
**mutation ledger**.

**Structured orchestration, not an LLM free-for-all.** The LLM classifies intent, extracts *raw*
slots, and phrases replies from code-supplied facts. **Code** does relative-date resolution, coverage
gating, fee math, and the mutation itself — the LLM never guesses a date, a fee, or who is eligible.

**Retrieval** is hybrid **BM25 + dense (`bge-base-en-v1.5`) fused with Reciprocal Rank Fusion**
(digits/ZIPs/prices need lexical; prose needs semantic), with the dense store behind a swappable
`VectorStore` protocol (Chroma default, NumPy-exact reference for a parity check), and a confidence
band that drives **abstention → handoff** when the corpus likely can't answer.

**Compilation completeness at scale.** Per-entity facts (e.g. a diagnostic fee per service line) are
compiled by **iterating the known entities** with a targeted retrieval each, and documents are
selected by a **dual criterion** (aggregate fusion score *or* a single strong dense match), so a fact
buried in one document still gets extracted even if that document doesn't dominate a top-N — this is
what scales to many documents.

### Repository layout

```
src/meridian/
  config.py / clock.py     settings; injected Clock (no datetime.now in business logic)
  api_contract.py          Booking-API contract constants (doc 12) + a federal-holiday stub — NOT facts
  domain/                  pure types: enums, value objects, errors
  ingestion/               parse → structure-aware chunk → build index   [document-agnostic]
  retrieval/               embedder, bm25, hybrid (RRF), confidence/abstention
  llm/                     Anthropic structured-output client + on-disk record/replay cache
  extraction/              COMPILE-TIME: capability schemas + grounded extractors + compile.py
  knowledge/               RUNTIME: loader + coverage/fees/branches (deterministic logic)
  api_client/              typed Booking API client (HTTP) + in-process double
  tools/                   LLM tool surface (READ_ONLY vs MUTATING) + pydantic arg schemas
  agent/                   LangGraph state/nodes/graph/prompts/runner
  guardrails/              emergency (rules-first), scope, injection, fee-no-waive, limits
  tracing/                 TurnTrace (the eval + observability contract)
  cli.py                   composition root + interactive REPL + scripted demo
app/                       FastAPI mock Booking API + in-process double (reads data/extracted/fees.json)
server/                    minimal web-demo server (optional; repo + eval run without it)
web/                       static demo page (vanilla JS, no build step)
eval/                      datasets + harness (safety invariants, correctness, retrieval) + results.md
data/                      corpus (md) · index (chunks/vectors/bm25) · extracted (compiled facts) · llm_cache
files/                     the input PDFs (just the current sample; swap in any folder of PDFs)
tests/                     unit / api / tools / agent / server
```

---

## Safety & guardrails

- **Emergency first, recall-biased.** A committed keyword set (sourced from the emergencies FAQ) runs
  *before* anything else; an LLM paraphrase-catch is layered on as a **union** that can only *add* an
  emergency, never veto one. A detected emergency goes straight to the 24/7 line and **never** to a
  booking. Proven by the eval (recall = 0 misses) and now exercised by an emergency message that also
  carries a complete booking (the "never book an emergency" half).
- **Confirm-before-commit**, guaranteed structurally (topology + capability split + per-turn assertion)
  and cross-checked by the mutation ledger. No mutation precedes an approved confirmation.
- **Prompt-injection defense.** Retrieved text is fenced and labelled untrusted; the read-only/mutating
  capability split means a successful injection still can't mutate; web output is rendered as text
  (never HTML), so model output can't inject markup.
- **Fees are never waived by the model** — they are computed by code from compiled records.
- **Abstention.** Low retrieval confidence (or an answer that fails the groundedness check) → handoff,
  rather than an uncited guess.
- **Determinism.** Temperature 0, an injected frozen clock (a CI grep bans `datetime.now` in business
  logic), deterministic tie-breaks, and a committed LLM cache for keyless replay.

See [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) for the data conflicts found in the source pack (e.g. ZIP
22046, the Fri/Sat date, 2-hour vs 4-hour windows) and exactly how each is handled.

---

## Evaluation — results summary

`make eval` runs a **functional conformance suite** (not a powered statistical benchmark) through the
*real* agent over the in-process Booking double, scored on a trust hierarchy and reproducible offline
bit-for-bit. Full report: [`eval/results.md`](./eval/results.md).

| | Result |
|---|---|
| **Emergency recall** (never miss / never book) — *categorical hard gate* | **0 misses / 3** |
| **Confirmation-gating** (no mutation before approval, proven vs the mutation ledger) — *hard gate* | **0 violations / 8** |
| Deterministic correctness (intent / route / action effects / citations / facts) | **16 / 16** |
| Retrieval (knowledge cases) | **doc recall@5 = 100%, MRR = 1.00** |

The two safety invariants are **categorical** (zero tolerance) and proven against the mock API's
mutation ledger, not the agent's self-report. The harness **fails the build if its committed inputs
are missing** (a skipped safety gate is indistinguishable from a passing one), and every
mutating-surface case is automatically covered — you can't add a booking case that escapes the gate.
Generalization to unseen documents is proven separately by `tests/unit/test_generalization.py`
(a synthetic document with new counties, glyph artifacts, and ZIP-range gaps compiles correctly
through the *unchanged* extractor).

---

## Key design decisions

- **Schema vs data** (above) — the only way to honour "no hand-authored facts" at 10,000 documents.
- **Deterministic booking-critical path** — RAG *explains*; code *computes the number / decides
  eligibility*. Exact figures and who-we-book are guaranteed by code over compiled records.
- **Confirm-before-commit by construction**, not by prompt instruction.
- **Hybrid retrieval + RRF**, tuned for a small corpus (`k≈15`, not web-scale 60), with the dense
  store behind a swappable `VectorStore` protocol and a NumPy-exact backend retained for a parity
  check.
- **Keyless, record/replay LLM cache** — content-addressed, committed, so every result reproduces
  offline at temperature 0.
- **One service module** shared by the FastAPI mock and the in-process double, so the HTTP demo and the
  fast/keyless eval exercise identical business logic.

## What we deliberately left out (prototype scope)

A full React/Vite SPA (→ a minimal static page); a standalone heavy serving service (→ one lightweight
process using the in-process double); Ragas in the core/headline (→ an optional, import-guarded
directional cross-check); a persistent booking DB (in-memory seeded); real auth / SMS / email
(`confirmation_sent` is simulated; the demo is unauthenticated); a cross-encoder reranker
(deliberately omitted — a localized add to `HybridRetriever.search` if chunk-level metrics show a
precision gap); a full federal-holiday calendar (a small documented stub); SSE streaming;
South-region coverage
(intentionally `unknown` → escalate, since no source document defines it); fine-tuning. Each is a
right-sizing decision for a take-home, not an oversight.

## Debugging methodology

The system is built so bugs **reproduce deterministically** and are caught by **independent layers**:

1. **Determinism by construction** — frozen clock, temperature 0, committed LLM cache → any bug
   reproduces on every run; the eval's "run-twice-and-diff" is clean.
2. **Three verification layers per phase** — unit/integration tests (keyless), a live end-to-end
   smoke, and an **adversarial multi-agent review** (independent agents probe for failure modes;
   each finding is re-verified by a skeptic before it's accepted).
3. **The eval as a regression gate** — categorical safety invariants (emergency, confirm-gating)
   proven against the mutation ledger run in CI; a routing/grounding/action regression fails the build.
4. **`TurnTrace` as the observability contract** — every turn records its route, retrieval confidence,
   each tool call (with capability tag), the proposed action and confirmation outcome, and any
   handoff; diagnosing a turn means reading its trace.

This methodology found and fixed real bugs, e.g. a coverage record missing 2/17 ZIPs (fixed with
parent-document extraction over full document text), a `TurnTrace` silently dropped across the
confirmation interrupt (fixed by re-emitting the mutated trace so the checkpoint persists it), and —
in the adversarial review of the eval *itself* — a status assertion (`"12"`) that passed vacuously
because "12" also appears in the booking id and the appointment window. The retrieval/chunking
evolution (fixed-size → sliding-window → structure-aware) and the move from hand-authored YAML to
grounded extraction are written up in [`DESIGN_EVOLUTION.md`](./DESIGN_EVOLUTION.md).

---

## How to extend / add documents

1. Put PDFs in `files/` (or repoint `MERIDIAN_FILES_DIR`). 2. `make ingest`. 3. `make extract`.
4. Done — **no code changes**. New service-area / pricing / hours documents flow through the same
grounded-extraction path; per-entity facts iterate the known entities. Adding a *new kind* of
capability = register one extractor (schema + query) in `extraction/` and a loader in `knowledge/` —
still zero hand-authored data.

## License

MIT.
