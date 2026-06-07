# Meridian Assistant — Run Playbook

Everything you need to run the project: setup, the web UI, the CLI, the evaluation harness, the
mock Booking API (Swagger), and the test gate — with exact commands and what to expect, plus
**sample questions to try**.

> **Two things up front**
> - **No API key is needed** to run the eval, the tests, the scripted demo, the suggested web prompts,
>   **or any of the sample questions in §6** — the agent's temperature-0 LLM calls **replay from a
>   committed cache** (all 17 verified keyless). Only *reworded / new* questions in the live CLI / web
>   UI call the model, so they need a key (see *Optional: live key*).
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
python -m pytest                                     # 150 tests
python -m ruff check src tests app eval server       # lint
python -m mypy src app eval server                   # types
#   all three at once:  make check
```
**Expect:** `150 passed`; ruff `All checks passed!`; mypy `Success: no issues found`.

---

## Optional: a live API key (only for free-typed questions)

The eval, tests, scripted demo, and suggested web prompts are keyless. To free-type *new* questions
in the CLI/web UI (anything not in the cache), provide a key:

```bash
cp .env.example .env          # Windows: copy .env.example .env
# then edit .env →  ANTHROPIC_API_KEY=sk-ant-...
```

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
  live agent was asked. Try a suggested prompt, or set a key (*Optional: live key*).
- **First run is slow / network call** — that's the one-time embedding-model download; subsequent runs
  are offline.
- **Port already in use** — change `--port` (e.g. `--port 8801`), or stop the other server (`Ctrl+C`).
- **Reset the demo state** — bookings live in memory; restart the server/CLI to re-seed.

---

See `README.md` for design rationale, `docs/architecture.html` for the visual workflow,
`ASSUMPTIONS.md` for data conflicts + guardrails, `DESIGN_EVOLUTION.md` for the debugging story,
and `docs/path_to_production.md` for the scaling plan.
