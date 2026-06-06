# Meridian Home Services — AI Contact-Center Assistant

A prototype AI assistant for a mid-market home-services company (HVAC / plumbing /
electrical). It:

1. **Answers** policy/FAQ questions **grounded in the provided knowledge pack, with citations**;
2. Runs an **agentic flow** — checks ZIP service-area eligibility, then **creates or reschedules a
   booking** via a mock Booking API, with input validation and a **confirm-before-commit** step;
3. **Hands off to a human** when confidence is low, the request is out of scope, or info is missing;
4. Ships a **small evaluation harness** measuring retrieval quality and answer/action correctness.

> **Status:** under active construction. The authoritative design is in
> [`PLAN.md`](./PLAN.md); data conflicts and decisions are in
> [`ASSUMPTIONS.md`](./ASSUMPTIONS.md).

## Quickstart

Requires **Python 3.11** (see ASSUMPTIONS for the 3.11-vs-3.12 note) and git.

```bash
# 1) create a virtual environment
py -3.11 -m venv .venv            # Windows
# python3.11 -m venv .venv        # macOS/Linux

# 2) activate it
.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate       # macOS/Linux

# 3) install (core + dev tools; Ragas is an OPTIONAL extra, not required)
make install                      # or: python -m pip install -e ".[dev]"

# 4) build the retrieval index (or use the committed one)
make ingest

# 5) talk to the assistant
make cli                          # or: python -m meridian.cli
```

**No `make` on Windows?** Run the underlying commands directly, e.g.
`.venv\Scripts\python -m pytest`, `.venv\Scripts\python -m meridian.cli`.
Every `make` target is a thin wrapper around one such command (see the `Makefile`).

The **deterministic eval tier runs without an API key**; only the live agent and the
judged eval tier need `ANTHROPIC_API_KEY` (copy `.env.example` → `.env`).

## Architecture at a glance

| Capability | Where it lives |
|---|---|
| Grounded answers + citations/traceability | `src/meridian/ingestion`, `src/meridian/retrieval`, agent `respond` node |
| Agentic ZIP→create/reschedule + confirm-before-commit | `src/meridian/agent`, `src/meridian/tools`, `app/` (mock Booking API) |
| Safe fallback / human-handoff | `src/meridian/agent` (safety + routing), `src/meridian/guardrails` |
| Eval harness | `eval/` |

Booking-critical logic (service-area coverage, cancellation fees, appointment windows)
is **deterministic structured code** (`app/service.py`, `src/meridian/knowledge`), never RAG.
RAG handles *prose* knowledge (pricing bands, plans, warranty, payments, FAQs) with citations.

## Key design decisions · What we deliberately left out · Debugging methodology

Filled in as the build lands; see `PLAN.md` for the full rationale and `ASSUMPTIONS.md`
for the data conflicts we found and how we handled them.

## License

MIT.
