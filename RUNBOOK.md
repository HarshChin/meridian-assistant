# Meridian Assistant — Run Playbook

Everything you need to run the project: setup, the web UI, the CLI, the evaluation harness, the
mock Booking API (Swagger), and the test gate — with exact commands and what to expect, plus
**sample questions to try**.

> **Two things up front**
> - **No API key is needed** to run the eval, the tests, the scripted demo, the suggested web
>   prompts, **or any of the sample questions in §6.** These are **not canned strings**: the agent's
>   temperature-0 LLM calls **replay from a committed record/replay cache** of the model's *real*
>   prior outputs (keyed by a SHA256 of the exact request). At temperature 0 a replay is
>   indistinguishable from a live re-call, so the eval, the demo, and CI all reproduce **offline**.
>   The booking-critical path (ZIP eligibility, fee math) is deterministic code over compiled facts —
>   it never calls an LLM, so it's keyless regardless. **Want to test something we *didn't* pick? Add
>   your own key and free-type any new question — the full live agent runs** (see *§ Running it live:
>   bring your own question*, which also shows how to prove the keyless claim yourself).
> - The retrieval **index, compiled facts, and LLM cache are committed**, so you can skip `ingest`/
>   `extract` and run immediately. The **first run downloads the embedding model once**
>   (`bge-base-en-v1.5`, ~tens of MB) — needs internet that once, then it's offline.

---

## 0. Setup (once)

Requires **Python 3.11** and git.

```bash
# clone, then from the repo root:

# 1) create + activate a virtual environment
python -m venv .venv
#   Windows (PowerShell):   .venv\Scripts\Activate.ps1
#   macOS / Linux:          source .venv/bin/activate

# 2) install core + dev tools  (Ragas is an optional extra, NOT required)
python -m pip install -e ".[dev]"          # shortcut: make install
```

After activating the venv, every command below is just `python -m …`. On macOS/Linux you can also
use the `make` shortcuts shown in parentheses. On Windows without `make`, use the `python -m` form
(or `.venv\Scripts\python.exe -m …` without activating).

---

## 1. The web UI  ▶ best first impression

```bash
python -m uvicorn server.app:app --port 8800        # (make demo-web)
```
Open **http://localhost:8800**.

- The first question takes ~3–5 s while the retrieval model loads — **ask one throwaway question to
  warm it up**, then present.
- Click a **suggested prompt** (these replay keyless) or type your own.
- Watch for: **citation chips** under answers, the **confirm modal** on a booking (it commits *only*
  after you click **Approve**), and the **trace** panel (`▸ trace`) showing intent / route / tools.

---

## 2. The CLI

```bash
# interactive REPL (type a message; commands: /trace, /quit)
python -m meridian.cli                                # (make cli)

# scripted, deterministic replay across capabilities, with decision traces
python -m meridian.cli --demo --trace                # (make demo)
```
In the REPL, when a booking is proposed you'll be prompted `Confirm: … [y/N]` — type `y` to commit,
anything else to decline. `--demo` auto-approves and prints a trace line per turn.

**Expect** (`--demo`): a cited plan answer → a Sunday-surcharge answer → an emergency handoff → a
booking that commits as `BK-101` after approval → an out-of-area decline → an en-route status.

---

## 3. The evaluation harness  ▶ the correctness/safety story

```bash
python -m eval.harness.runner                        # (make eval) → regenerates eval/results.md
```
**Expect:**
```
cases: 22/22 passed (100%)
emergency recall: misses=0/3
confirmation-gating: violations=0/11
retrieval: recall@5=100% MRR=1.00
CI gate: PASS
```
Open **`eval/results.md`** for the full report (categorical safety invariants, deterministic
correctness per case, retrieval metrics). It's **keyless** — runs with no API key.

---

## 4. The mock Booking API + Swagger docs

```bash
python -m uvicorn app.main:app --port 8000           # (make api)
```
Open **http://localhost:8000/docs** for the interactive Swagger UI (the doc-12 contract:
`POST/GET/PATCH /v1/bookings`).

- The API is **channel-scoped auth'd**. In Swagger click **Authorize** and use the bearer token
  **`mock-agent-token`** (other channels: `mock-ivr-token`, `mock-web_chat-token`, `mock-email-token`).
- Try **`GET /v1/bookings/BK-003`** → an *en-route* HVAC booking, ETA 12 min. (Calls without a valid
  token return **401**; owner-only PII like the technician name is withheld unless you pass the
  matching `customer_id`.)

curl equivalent:
```bash
curl -H "Authorization: Bearer mock-agent-token" http://localhost:8000/v1/bookings/BK-003
```

---

## 5. The test gate

```bash
python -m pytest                                     # 151 tests
python -m ruff check src tests app eval server       # lint
python -m mypy src app eval server                   # types
#   all three at once:  make check
```
**Expect:** `151 passed`; ruff `All checks passed!`; mypy `Success: no issues found`.

---

## Running it live: bring your own question

**You don't need a key to evaluate this project, and nothing is hidden behind one.** The eval, the
full test suite, the scripted demo, the suggested web prompts, and every sample question in §6 run
**offline with no key** — and we'd encourage you to confirm that first.

### What the committed cache actually is (and why keyless replay is legitimate)

Every agent LLM call (`claude-sonnet-4-6`, **temperature 0**) goes through a genuine
**record/replay cache** in `data/llm_cache/`. The first time each call ran *with* a key, the **real**
model response was captured and frozen on disk; the file is named by a `SHA256` of the full request
(model id, system prompt, user message, output schema — see `src/meridian/llm/client.py:72`), **not**
by the question text. So these are the model's actual outputs, not hand-written answers. Because
temperature 0 is deterministic, replaying a cached response is **indistinguishable from re-calling
the model for that identical input** — which is exactly why the cache is committed: you (and CI) get
identical, reproducible results with zero network and zero key. (We rely on temp-0 determinism for
in-corpus reproducibility; we don't claim byte-identical behavior across future model revisions, only
that *these committed recordings* reproduce the documented results.) The booking-critical path (ZIP
eligibility, fee math) is deterministic code reading compiled facts from `data/extracted/` and
**calls no LLM at all**, so bookings are keyless no matter what.

> **Prove it yourself.** A cache key is content-addressed over the *exact* request, so a reworded
> question is a different hash — a cache **miss**. To see that the answers come from recorded model
> calls (not hardcoded strings): rename `data/llm_cache/` aside and re-run a §6 prompt keyless — it
> raises `LLMUnavailableError` (a clean `503` in the web UI) instead of answering. To audit the
> keyless claim cleanly on this checkout, make sure **no key is present** first: `config.py` loads
> `.env`, so a key sitting there would let a cache miss silently go live. Move `.env` aside and unset
> `ANTHROPIC_API_KEY`, then run `make eval` / the §6 prompts — they pass with **no key available**
> (`cases: 22/22`, `emergency: 0/3`, `confirmation-gating: 0/11`, `recall@5 100%/MRR 1.00`; full
> suite `151 passed`).

### Want to test a question of your own? Please do.

This is a real, multi-node LangGraph agent (safety → classify → retrieve → plan/answer →
validate → confirm → commit → respond), **not** a scripted bot — so go ahead and ask it something
new. Add a key and the **entire live agent runs end to end in real time**: safety screen → intent
classify → hybrid retrieval → plan/answer → (for bookings) validate → confirm-before-commit →
commit. It's the **same code path** as replay — only the cache lookup differs — so "works on the
recordings" means "works live on new input"; there is no separate scripted path. The fresh response
is then written into the cache too, so your new question becomes reproducible for the next person.

```bash
cp .env.example .env          # Windows: copy .env.example .env
# then edit .env →  ANTHROPIC_API_KEY=sk-ant-...
```

Then run `make cli` (or `make demo-web`) and free-type whatever you like. The only thing a key buys
is *reaching questions we never anticipated* — which is exactly what we'd want you to try. And
keyless mode never fabricates: with no key, a never-seen question deterministically surfaces
`LLMUnavailableError` rather than inventing an answer.

---

## 6. Sample questions to try

**Every prompt below replays from the committed cache — copy-paste them with no API key.** (Reword
one and the live agent answers it, which needs a key.) The demo clock is frozen at **2026-05-01**, so
use dates in **May 1 – June 30, 2026** (or `today`, `next Wednesday`). Seeded bookings: **`BK-001`**
(cancel), **`BK-002`** (technician/PII, owner `CID-1002`), **`BK-003`** (status/ETA), **`BK-005`**
(reschedule). New bookings you create get **`BK-101`, `BK-102`, …**.

### Grounded answers with citations *(capability 1)*
- `What's the difference between the Gold and Platinum maintenance plans?` → cited; **$249 vs $399**.
- `Is there a surcharge for a Sunday appointment?` → **+$125**, cited.
- `What is your no-show cancellation fee?` → **$75**, cited.

### Agentic booking: ZIP eligibility → confirm → commit *(capability 2)*
- `Book an HVAC tune-up at ZIP 22030 for 15th May 2026 in the morning. Customer id CID-5000.`
  → confirm modal → **Approve** → committed as **`BK-101`**.
- `My name is Priya, phone 703-555-0188, email priya@example.com. Book an HVAC repair at ZIP 22030 for 20 May 2026 at noon.`
  → books from **contact details** (no account id needed).
- `Move BK-005 to the afternoon, same day.` → reschedule that **keeps the date** → Approve.
- `I would like to cancel my booking BK-001.` → confirm → Approve (states any cancellation fee).

### Safe fallback / human-handoff *(capability 3)*
- `There's a burning smell coming from my electrical panel!` → **emergency** → 24/7 line, never a booking.
- `What's the weather forecast for tomorrow?` → **out of scope** → handoff.
- `I'd like to book an HVAC repair.` → **missing info** → asks one question (the ZIP).
- `Book an electrical repair at ZIP 20147 for May 16 2026 morning. Customer id CID-7001.`
  → **out of area** (Loudoun electrical) → declines with a citation, no booking.
- `Book an HVAC tune-up at ZIP 22030 for August 15 2026 morning. Customer id CID-5000.`
  → **out of the 60-day window** → explains the bookable range (May 1 – Jun 30).

### Nice extras
- `hi` · `what can you do?` → a friendly, in-role greeting.
- `What's the status of booking BK-003?` → **en route, ETA 12 minutes**.
- **PII guardrail (two messages):**
  - `What's the status of booking BK-002, and who's my technician?` → shares status, **withholds the technician**, asks you to verify the customer ID.
  - `What's the status of booking BK-002? My customer id is CID-1002.` → **verified → technician Marcus Webb**.

> Tip: **state a booking in one message** (e.g. ZIP + date + customer id together). Multi-turn
> slot-filling ("book HVAC" → "what ZIP?" → "22030") is a documented path-to-production item; the
> confirm round-trip itself *is* stateful, so propose → Approve always works.

---

## Troubleshooting
- **`make` not found (Windows)** — use the `python -m …` commands above; each `make` target is just a
  thin wrapper around one of them (see the `Makefile`).
- **"needs ANTHROPIC_API_KEY" / a 503 in the web UI** — that message wasn't in the offline cache, so the
  live agent was asked. That's the system working as designed (it never fabricates an answer it can't
  ground in a real model call). Try a suggested prompt, or add a key (*§ Running it live: bring your
  own question*).
- **First run is slow / network call** — that's the one-time embedding-model download; subsequent runs
  are offline.
- **Port already in use** — change `--port` (e.g. `--port 8801`), or stop the other server (`Ctrl+C`).
- **Reset the demo state** — bookings live in memory; restart the server/CLI to re-seed.

---

See `README.md` for design rationale, `docs/architecture.html` for the visual workflow,
`ASSUMPTIONS.md` for data conflicts + guardrails, `DESIGN_EVOLUTION.md` for the debugging story,
and `docs/path_to_production.md` for the scaling plan.
