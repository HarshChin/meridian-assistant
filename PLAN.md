# Meridian Home Services — AI Contact-Center Assistant (Implementation Plan)

## Context

High-stakes take-home: a working prototype AI assistant for **Meridian Home Services** (fictional
HVAC/plumbing/electrical; ~180 staff; 11 branches; 3 regions; ~8,500 interactions/mo). It must
(1) answer policy/FAQ questions **grounded in the provided docs with citations**, (2) run an
**agentic flow**: check ZIP service-area eligibility → create/reschedule a booking via a mock API,
with input validation + a **confirm-before-commit** step, (3) **safely hand off to a human** when
confidence is low / out of scope / info missing, and (4) ship a **small eval harness** measuring
retrieval quality and answer/action correctness. Deliverables: running repo + README (run / design
decisions / what we deliberately left out / **debugging methodology**); eval harness + **short
results summary**; one-page **path-to-production** note; assumptions + guardrails.

**Repo today:** `D:\meridian\` is a private git repo with the **13 source PDFs** in `files/` + this
`PLAN.md`; no app code yet. The Booking API is a **spec only** (doc 12) — we implement it. The test
set is **20 labeled customer messages** (doc 13) — we convert + extend it.

**This plan has been stress-tested by three independent adversarial senior reviews** (product/scope,
architecture/failure-modes, eval methodology). Their findings are folded in below; the guiding
principle that emerged: **right-size for a take-home — make the graded core flawless, keep the demo
shell minimal, and be visibly honest about limits.** A submission that doesn't `git clone && run`
on the reviewer's box is the #1 offer-killer, so every extra moving part was scrutinized.

---

## Locked technology decisions

| Area | Choice | Justification |
|---|---|---|
| Generation LLM | **Anthropic Claude** — Sonnet for the agent/answers **and as the eval groundedness judge**; Haiku for cheap intent-classify + emergency paraphrase-catch | Strong tool-calling + grounded answers; judging with a *stronger, different* model than the generator avoids same-family self-preference bias. |
| Orchestration | **LangGraph** | Earns its keep via the durable **checkpointer** (multi-turn slot state) + `interrupt()` HITL on the CLI. We explicitly acknowledge a hand-rolled loop would also work and use the simpler token pattern for HTTP (below) — that contrast is deliberate, not over-tooling. |
| Embeddings | **Local ONNX `bge-base-en-v1.5` (768d) via `fastembed`** | Free, offline, reproducible; ONNX dodges the torch/3.14 wheel trap. (First-run model download documented; vendored/cached for the keyless tier.) |
| Retrieval | **Hybrid BM25 + dense (Chroma, embedded) fused with RRF**, behind a swappable `Retriever` interface — **with empirical per-leg justification** | Digits/ZIPs/prices need lexical; prose needs semantic. RRF `k≈15` (tuned for a ~150-chunk corpus, *not* web-scale k=60). If fusion doesn't beat the best single leg at recall@5, we ship the simpler leg and say so. |
| Knowledge answering | **Pure RAG + citations** for *prose* knowledge (plan comparisons, warranty/payment policy, FAQ); **computed fees/eligibility stay in code** | RAG *explains*, code *computes the number*. Exact figures guaranteed by deterministic fact-match. |
| Mock Booking API | **FastAPI app + in-process double sharing one `service.py`** | Realistic HTTP demo + fast/keyless/deterministic eval via the same business logic. |
| Interface | **CLI REPL (canonical, graded, eval driver) + a *minimal static HTML* demo** (vanilla `fetch`, no Node build) over a lightweight serving API | CLI is the testable core; static page gives a visual confirm-modal/citation demo with near-zero clone-time risk. **Repo runs fully without the web demo.** |
| Evaluation | **Custom deterministic harness (CI gate) + Sonnet groundedness judge (judged tier) + Ragas (OPTIONAL extra, import-guarded, directional cross-check)** | Deterministic tier owns reproducible action/handoff/gating + retrieval; Sonnet judge covers what fact-match can't; Ragas triangulates but never gates and isn't headline. |
| Hygiene | Python **3.12 venv**, `pyproject.toml` (Ragas behind `[ragas]` extra), pinned deps + committed lockfile, **ruff/mypy/pytest**, google-style docstrings, type hints | Core installs/runs **without** Ragas; a Ragas install failure can't block the core or CI gate. |

**Prereqs/risks:** Python **3.12 venv**. `ANTHROPIC_API_KEY` needed for live agent + judged tier;
**deterministic tier runs keyless**. Dependency-conflict surface (ragas↔langchain↔chromadb↔
onnxruntime) is contained by the optional-extra isolation + a committed lockfile.

---

## Assumptions & data conflicts (→ `ASSUMPTIONS.md`; surfaced in `results.md`)

1. **ZIP 22046 (gold #3) vs doc 01's out-of-area policy.** Doc 01 lists Fairfax `22030–22039,
   22041–22044` and says unlisted ZIPs → escalate; gold #3 ("book Falls Church 22046") *contradicts*
   that — and #3/#9 are the *same* situation with opposite gold. **Decision (honest treatment):** a
   labeled `overrides.yaml` (branch-city ZIP, `source: inferred-from-branch-location doc08,
   confidence: low`). The eval **grades the disclosure invariant** — "never present inferred
   eligibility as documented fact; the low-confidence override flag is surfaced" — **not** "a booking
   was created." A clean in-range case (**22032**, used by the API spec itself) provides the
   unambiguous booking-success test. The conflict is named in `results.md`.
2. **"Friday the 24th" (gold #5) is a Saturday** in 2026 — source self-contradiction. Treat the ISO
   date as authoritative; a **calendar-consistency assertion** (`weekday(date)==stated`) flags it;
   documented.
3. **Window mapping:** FAQ doc 09 says "2-hour windows" but the API example uses full bands
   (`afternoon→14:00–18:00`). **Follow the API spec** for booking math: `morning 07:00–11:00 /
   midday 11:00–14:00 / afternoon 14:00–18:00 / first_available→deterministic`. Customer-facing: quote
   the API band; if asked about "2-hour windows," explain the day-of arrival window narrows.
4. **South region:** 5 branches in doc 08, **no ZIP-coverage doc** → any South/unknown ZIP =
   `unknown` (distinct from documented `no`) → clarify/escalate. Not invented.
5. **Central branch table absent** (doc 02): documented assumption from doc 08 (Rockville/Columbia/
   College Park; UMD 20742 → College Park).
6. **Channel mapping:** Phone→`ivr`, Email→`email`, CLI→`agent`, web→`web_chat`.
7. **Idempotency key** is an added safety control (not in doc 12) — noted so it doesn't read as a
   misread spec.

---

## Architecture

### Repo layout
```
meridian/  (D:\meridian — private git repo)
├── pyproject.toml (core + [ragas] extra)  uv.lock/requirements.lock  README.md  ASSUMPTIONS.md  PLAN.md  .env.example  Makefile  .gitignore
├── files/                         # 13 source PDFs (provided)
├── src/meridian/
│   ├── config.py  clock.py        # pydantic-settings; Clock/FrozenClock/SystemClock (injected; no datetime.now in logic)
│   ├── domain/                    # enums.py (CreateStatus|LookupStatus|ModifyStatus|CoverageEligibility — SEPARATE), booking.py, errors.py
│   ├── windows.py                 # window↔band map + deterministic first_available + resolve_relative_date(text, now)
│   ├── knowledge/coverage.py      # segmented ZIP parser → CoverageDecision{eligibility, flags...}; branches.py
│   ├── ingestion/                 # extract.py (pdfplumber), tableizer.py, chunker.py, build_index.py
│   ├── retrieval/                 # retriever.py (protocol), store.py (Chroma + NumPy alt), embedder.py, bm25.py, hybrid.py (RRF, chunk_id tiebreak), confidence.py
│   ├── api_client/                # client.py (HTTP) + models.py (mirror doc 12, per-op response models + validators)
│   ├── tools/                     # registry.py (tags READ_ONLY|MUTATING), schemas.py, knowledge_search/service_area/bookings/escalate
│   ├── agent/                     # state.py (incl. slots), graph.py, nodes/* (safety,classify,retrieve,plan_act,validate,clarify,confirm,commit,respond,handoff), prompts/*, runner.py
│   ├── guardrails/                # emergency.py (rules-primary union), fee_policy.py, pii.py, scope.py, injection.py, limits.py
│   ├── tracing/trace.py  cli.py
├── app/                           # FastAPI mock Booking API + in-process double (shared service.py = ALL fee/window/coverage-gate/waiver/ledger logic); auth.py (channel-scoped); seed.py; ledger.py (independent mutation ledger)
├── server/app.py                  # lightweight FastAPI: serves web/ + POST /sessions/{id}/messages + /confirm (propose-token, stateless); uses runner + in-process double
├── web/                           # static demo: index.html + app.js + style.css (vanilla; NO build step) — chat, citation chips, confirm modal, trace <details>
├── eval/                          # datasets/(seed.jsonl, extended.jsonl, chunk_qrels), harness/(runner, metrics, judge, ragas_eval[guarded]), cassettes/
├── data/  service_area/*.yaml(+overrides)  branches.yaml  corpus/*.md  index/(chunks.jsonl, chroma/, bm25.pkl, manifest.json)
├── scripts/{ingest.py, run_api.py}  tests/{unit,api,tools,agent}/ conftest.py
```
**Dependency direction:** `domain/` → `app/service.py` (sole owner of fee/window/coverage math) →
`api_client/` → `tools/` → `agent/` → `eval/ + server/ + cli`; `web/` → `server/`. The LLM never
recomputes fees/coverage. **Two retrieval paths:** booking-critical lookups = structured code;
prose knowledge = RAG.

### Ingestion
`pdfplumber` (MIT; tables + clean text; no OCR) → extract **once** into committed, human-verified
`data/corpus/*.md` + `chunks.jsonl`. **Structure-aware chunking by `chunk_type`:** table → one chunk
per row (title+headers+section prepended) **+ a whole-table chunk** (comparisons); FAQ → one chunk
per Q&A; prose → by heading (never split a fee-tier/trigger list). Rich citation metadata
(`chunk_id`, doc_id, version, section, page, char span). Booking-critical data is the **hand-verified
YAML**, not the index. Commit `corpus/`+`index/`; `manifest.json` pins embed-model id+revision + corpus
hash; `make ingest` optional (committed index canonical) with a staleness guard.

### Retrieval
**Embeddings:** `bge-base-en-v1.5` (768d, normalized) with bge's **asymmetric query/document
prefixing** — already *task-aware for retrieval*. Full `task_type` embeddings (Nomic v1.5 local;
Gemini/Voyage API) were considered and **deliberately not adopted** (marginal gain on a ~150-chunk,
lexically-distinctive corpus; API variants break offline/reproducible) — documented as a right-sizing
decision.
**Index:** **Chroma embedded (HNSW)** is the default store, behind the `Retriever` interface. HNSW is
*over-spec'd* at ~150 chunks (ANN targets 10⁵+); at this N it returns **effectively-exact** top-k, so
we keep it for the **vector-store pattern + persistence + metadata filtering + scale story**, not for
ANN speed. Determinism pinned: single-thread build, fixed HNSW params, **`chunk_id` tie-break**; a
**NumPy exact backend** is retained behind the same interface and a **parity test asserts HNSW top-k ==
exact top-k** on the eval queries (turns the over-spec into a validation artifact).
**Hybrid:** BM25 Okapi (keep digits) + dense, **RRF k≈15** (tuned for this scale, not web-scale 60),
justified empirically per-leg (ship the simpler leg if fusion doesn't beat it at recall@5).
**No reranker** by default (right-sized; hook left in `hybrid.py`); the chunk-level metrics decide — if
a precision gap appears, opt in `flashrank` (ONNX, offline) or `bge-reranker-v2-m3`.
**Abstention** (`confidence.py`, no LLM): top dense-cosine + margin → HIGH/MED/LOW; LOW on grounded-only
→ handoff; **thresholds frozen on a held-out slice** (not the reported set); operating point shown via
a small PR curve. Retrieval eval is **chunk-level (primary)** + doc-level (lenient bound), per-leg
(dense/bm25/fused).

### Mock Booking API (`app/service.py` = the correctness core)
Implements doc 12: `POST/GET/PATCH /v1/bookings`, **channel-scoped bearer auth enforced** (reject
channel↔token mismatch). **Three separate status enums** (POST `confirmed|pending_availability|
out_of_area`; GET `confirmed|en_route|completed|cancelled|no_show`; PATCH `rescheduled|cancelled`) +
`CoverageEligibility` — response models reject out-of-set values, and enforce **conditional
nullability** (`tech_eta_minutes ⇔ en_route`; `invoice_total ⇔ completed`). **All fees in code:**
cancellation matrix `Δ>24h→$0 / 2h≤Δ≤24h→$35 / Δ<2h|no_show→$75` (exact 24:00:00/2:00:00 tie tests),
no-show **waived once/12mo/customer** (sets `waiver_used`); same-day-reschedule-as-late-cancel;
**after-hours/Sunday/holiday surcharge** (+$75 / +$125; minimal holiday set or abstain on holidays);
**`warranty_return ⇒ diagnostic_fee=0`**; same-day-repair diagnostic waiver; emergency dispatch fee
($99 plumbing/$89 HVAC) distinct + not waived. **Idempotency key** = hash(customer, service, job, zip,
date, window) → same `booking_id` on dupe (closes double-confirm race). **PII gate on GET:** without
matching `customer_id`, return only `status/appointment_window/tech_eta_minutes`; withhold
`tech_name/notes/invoice_total/customer_info`. **Mutation ledger** (`ledger.py`) records every
state-changing op with a sequence number; mutating endpoints require a **commit-nonce** minted only by
the confirm path. Deterministic `BK-XXXXXXXX` (seeded counter/hash).

### Coverage logic (`coverage.py`)
**Segmented range parser** (multi-range + singletons; **gaps are NOT covered** — 22040, 22210–22212
must test as not-covered). `check_coverage(zip, service) → CoverageDecision{eligibility:
yes|pending|no|unknown, region, county, branch, overflow, flags{same_day_blocked, sub_contracted,
surcharge_possible, refer_partner, coordination_flag}, citation}`. Edges: Alexandria electrical
`pending` = **in-area but no booking** (≠ out_of_area); Loudoun plumbing `yes`+`sub_contracted`+
`same_day_blocked`, electrical `no`; PG electrical `no`+`refer_partner:EcoPower`; 20742 `coordination_flag`;
South/unknown `unknown` (≠ `no`). Exhaustive boundary unit tests incl. gap ZIPs. (P1, no LLM.)

### LangGraph agent
**State** (TypedDict): messages, channel, now (injected), intent(+conf), **slots** (reducer),
retrieval_hits(+conf), proposed_action, tool_results, tool_iterations, pending_confirmation,
confirmation_decision, route, handoff, final_answer, citations, trace.
**Flow:** `safety_screen` (FIRST) → `classify` → route: handoff intents / grounded → `retrieve` →
`respond` (LOW→handoff) / action → `plan_act`. `plan_act` runs **read-only tools only** (registry
capability-split; a MUTATING call here raises `MutationOutsideCommitError`). Missing/ambiguous slots
→ **`clarify`** (ask one question, persist partial slots; ≠ handoff). Valid mutating proposal →
`validate` (pydantic) → `confirm` → `commit` (the **sole** holder of the mutating executor + nonce) →
`respond`. **Confirmation transport:** CLI uses `interrupt()` (single process); **HTTP uses a
stateless propose-`action_token` → `/confirm` executes** via the shared executor (avoids fragile
interrupt-over-HTTP). Relative dates resolved **in code** (`resolve_relative_date`), never guessed by
the LLM; "next week" with no day → clarify. Tool calls **serialized** (no parallel tool_use) for
trace determinism.

### Serving API + minimal web (`server/app.py`, `web/`)
Lightweight FastAPI serves the static page and two routes — `POST /sessions/{id}/messages` →
`answer`(+citations+trace) | `confirmation_required`(action+fee+window+`action_token`) | `handoff`;
`POST /sessions/{id}/confirm {action_token, decision}` re-validates server-side and executes via the
shared executor. Uses the **in-process Booking double** (one demo process). `web/` = `index.html` +
vanilla `app.js` (fetch) + `style.css`: chat, **citation chips**, **confirm modal**, trace `<details>`.
**Optional/non-blocking** — built last; repo + eval run without it.

### Guardrails
**Emergency FIRST, rules-primary union** (`emergency = rule OR llm`; committed trigger list verbatim
from doc 11; Haiku may only *add*, never veto; conditional triggers <40°F/>95°F → one clarify) →
immediate handoff to **1-800-555-0190**, never a booking · **fees never waived by the model**
(server-computed) · PII/ownership gate · **prompt-injection defense**: retrieved text fenced + labeled
untrusted, mutating capability-split (a successful injection still can't mutate), `booking_id` in a
mutating call must trace to a prior tool result, web output escaped · out-of-scope detection · tool-
iteration cap · idempotency.

### Determinism
FrozenClock injected (CI grep bans `datetime.now/utcnow/date.today/time.time/Timestamp.now`); global
`NOW=2026-01-20T09:00 ET` **but `now_override` is mandatory for every fee/boundary case** (a test fails
if a fee case inherits the canonical clock). Seeded bookings (BK-00391042/00483921/00512883 + en_route
sibling + reschedule target + waiver-used/available pair). Cache-key = SHA(model_id, full messages,
temp, top_p, max_tokens, tool-schema hash, system-prompt hash); **replay asserts 100% cache-hit**; all
judge samples cached. "Run-twice-and-diff" CI check.

---

## Capability → rubric mapping
| Capability | Where |
|---|---|
| 1. Grounded answers + citations/traceability | `ingestion/`+`retrieval/`+`respond`; citation tokens + chunk_id/page/span in `TurnTrace`; chips in `web/`. |
| 2. Agentic ZIP→create/reschedule + validation + confirm | `check_service_area`→`validate`→`confirm`→`commit`; pydantic args; mock API; CLI `interrupt()` / HTTP token-confirm. |
| 3. Safe fallback / handoff | `safety_screen` (emergency union) + route + confidence/abstention + `handoff` w/ `HandoffPayload`. |
| 4. Eval harness | `eval/` — deterministic CI gate + Sonnet judge + optional Ragas. |

---

## Evaluation harness (`eval/`) — framed as a *functional conformance suite*, not a statistical benchmark
**Test set (JSONL):** 20 seed + ~22 extended. Each gold fact records its **source span** (doc_id,
page, quoted substring) so it's auditable; multi-doc-synthesis cases flagged. Fields incl.
`now_override` (mandatory for fee cases), gold intent/route/handoff, gold_answer_facts (normalized),
**chunk-level** gold_citations, expected_tool_calls (ordered), `forbidden_tool_calls`,
`requires_confirmation_before`, expected_action_effects, abstention_expected, `data_conflict`.
**Extended adds:** confirm accept/decline; ZIP-boundary sweep (gap ZIPs, Alexandria-pending, Loudoun,
PG→EcoPower, 20742, South-unknown); #7 warranty_return (action, $0 diagnostic); out-of-60-day; invalid
enum; duplicate-booking; PII mismatch; **emergency mini-suite (≥10 positives across all 5 categories +
hard negatives like "AC weak but it's 70° out")**; **adversarial skip-confirmation + injection**;
off-topic; price-fabrication bait; low-confidence abstention. Paraphrase augmentation + ZIP sweeps are
reported **separately** (robustness), not folded into headline n.

**Metrics — trust hierarchy:**
- **Safety invariants (categorical, hard gates, non-zero exit):** emergency recall = **0 misses across
  N** (+ report precision/confusion); **confirmation-gating = 0 violations**, proved against the
  **independent mutation ledger** (no mutation precedes approved confirm; decline → ledger unchanged).
- **Deterministic (CI gate, keyless):** fact-match (normalized scalars/bands/times/phones; out-of-band
  number = fail); retrieval **chunk-level** recall@{1,3}/MRR/citation-hit (+doc-level bound, per-leg);
  intent/route/tool-set/ordered/arg-F1 (enum-validity hard fail); action-effects (fee/status/waiver);
  end-to-end task-success (uniform boolean); **containment** (correct vs *incorrect* containment).
- **Judged (optional, needs key/cassette):** **Sonnet** groundedness judge scoped to what fact-match
  can't do (unsupported-claim, scope, citation-supports-sentence); honest κ (state n+CI); prompt-
  sensitivity spot-check. **Ragas** (import-guarded) faithfulness/answer-relevancy as a *directional*
  cross-check — reference mapping unit-validated on 2 cases; **not** headline.
- **Operational:** latency p50/p95 + tokens/cost per turn (from the trace).

**Reproducibility honesty:** deterministic tier = bit-for-bit; judged tier = *replays one recording of
a nondeterministic model* (caveat stated); cache-hit asserted. `results.md` opens with a **scope &
honesty preamble** (n≈42, conformance not powered benchmark; CIs only on the pooled rate; safety claims
categorical), then tables strongest-first, then a **"Known data conflicts & how we graded them"**
section (22046, sub-contracted, Fri/Sat), then "what this eval can/can't tell you."

---

## Top failure modes & mitigations
Clone-time fragility → minimal static web + Ragas optional + committed lockfile + `make demo`. ·
Confirmation bypass → registry capability-split + commit-nonce + mutation-ledger + adversarial tests. ·
Emergency miss → rules-primary union, recall-biased, categorical gate. · Slot guessing → clarify node +
code-based date resolution. · Fee drift/wrong number → all fees in `service.py`, server-previewed. ·
Enum/coverage bugs → split enums + validators + segmented parser + gap-ZIP tests. · LLM/judge
nondeterminism → deterministic core, Sonnet judge on non-numeric only, temp 0, cached, tie-breaks,
serialized tools. · Dependency hell → Ragas optional-extra isolation + lockfile. · Injection → fenced
untrusted context + capability-split + output escaping.

---

## Path to production (one-pager)
Branch-specific policy via KB keyed `(branch_id, doc_type, version)`, branch→region→global resolution,
tenant-scoped retrieval, cite live version; South "branches-but-no-coverage" = deploy-time config
error. Scale ~8,500/mo: async + workers + rate limits + queue/backpressure; emergency sub-second
short-circuit; p50<3s/p95<8s; tenant/version-scoped + prompt caching. Harden: scoped-token rotation,
server-side enum/range/PII validation, in/out guardrail service, idempotency, swap mock for real
booking system **behind the same interface**, deterministic-FAQ/callback/emergency-line fallback when
LLM down, auth on serving API. Monitor: retrieval-hit, hallucination, handoff rate+reasons,
containment, CSAT, latency, cost, drift; **eval-in-CI gate** (emergency + gating hard); feedback→
labeling queue; canary/A-B + auto-rollback; human-review queue. Change from prototype: managed vector
DB (pgvector/Qdrant) keeping BM25 hybrid; LangSmith/OTel tracing; KB CMS with freshness/version pinning
(auto-flip "Pending Q2"); promote the static demo to a real SPA if/when warranted.

---

## Deliberately left out (prototype scope; in README/ASSUMPTIONS)
Full React/Vite SPA (→ minimal static page) · standalone heavy serving service (→ one lightweight
process using the in-process double) · Ragas in the core/headline (→ optional directional extra) ·
persistent booking DB (in-memory seeded) · real auth/SMS/email (`confirmation_sent` simulated; demo
unauthenticated) · cross-encoder rerank (hook left) · full federal-holiday calendar (small stub;
abstain on holidays) · member-tier same-day cutoffs in `first_available` (documented simplification) ·
SSE streaming · South-region coverage (intentional `unknown`→escalate) · fine-tuning.

---

## Build plan (each gate verifiable; deterministic core before any LLM; eval before the demo)
- **P0 Scaffold** — pyproject (core + `[ragas]` extra) + lockfile, src/ layout, config, clock, logging, Makefile, .gitignore, **README skeleton + ASSUMPTIONS started**. *Gate: `make lint` + empty `pytest` green; core installs without Ragas.*
- **P1 Domain + structured knowledge** — split enums; `windows.py` (+`resolve_relative_date`, `first_available`); `service_area/*.yaml`(+overrides)+`branches.yaml`; `coverage.py` (segmented parser). *Gate: ZIP boundary/gap tests (22040, 22210–12 not-covered), Alexandria-pending, Loudoun, PG→EcoPower, 20742, South-unknown, 22046-override-flagged. No LLM.*
- **P2 Mock API** — `service.py` (fee matrix + boundary ties, surcharge/warranty/same-day fees, waiver, window map, idempotency, PII gate, ledger, nonce), per-op response validators, auth (channel-scope), seed. *Gate: TestClient contract tests incl. exact 24h/2h boundaries, conditional nullability, PII withholding, channel mismatch, duplicate dedupe.*
- **P3 Ingestion + retrieval** — pdfplumber→corpus→structure-aware chunk→bge-base→Chroma; `Retriever`+RRF(k≈15, chunk_id tiebreak)+confidence; NumPy exact alt. *Gate: chunk-metadata snapshot; gold queries top-k at chunk level; per-leg metrics; **HNSW↔exact parity test**; abstention off-corpus; held-out threshold tuning.*
- **P4 Tools + client** — HTTP client + in-process double (shared service); registry READ_ONLY|MUTATING; schemas+validation. *Gate: mutating tool raises outside commit; read-only execute.*
- **P5 Agent** — state(+slots), nodes (incl. `clarify`, capability-split executors), graph, prompts, runner, guardrails (emergency union, injection), tracing. *Gate (FrozenClock+double, LLM mocked where needed): emergency short-circuit + paraphrases + no-booking; handoffs #8/#15/#18; booking confirm→commit (#3 disclosure + 22032 clean); warranty #7 ($0 diagnostic); reschedule no-fee #5; same-day fee+waiver #17 (now_override); status/ETA #4/#13 incl. else-branch; out-of-area #9; slot-fill clarify (no guessed date); adversarial skip-confirm = ledger empty.*
- **P6 CLI** — REPL over `runner.run_turn` (+`--frozen-clock`, auto-approve/deny); `make demo`. *Gate: scripted replay of all 20 + recorded transcript/GIF.*
- **P7 Eval** (graded; before the UI) — seed+extended JSONL (source spans), runner (mutation-ledger + per-case clock), metrics (chunk-level retrieval, fact-match, Sonnet judge, action, categorical safety, containment, latency/cost), **Ragas guarded**, `results.md`. *Gate: deterministic tier reproduces offline (100% cache-hit), report generated, hard gates pass, run-twice-diff clean.*
- **P8 Minimal web demo** (optional/non-blocking) — `server/app.py` (messages/confirm token pattern) + `web/index.html`+`app.js`. *Gate: browser: booking commits only after Approve; citations show; repo still runs fully without it.*
- **P9 Docs** — README (run/design/**deliberately-left-out**/**debugging methodology** captured *as we built*), ASSUMPTIONS, path-to-production, short results summary.

---

## End-to-end verification
1. `make ingest` (or use committed index).
2. `make api` + `make cli` → run all 20 messages; **booking commits only after explicit approval**; FAQ answers carry citations.
3. `make demo-web` → open the static page: chat, citation chips, **confirm modal** (commit only on Approve).
4. `make test` → unit/contract/agent green; ruff+mypy clean.
5. `make eval` (replay, keyless) → `results.md` shows retrieval (chunk-level, per-leg), fact-match, Sonnet-judge, action, containment, latency; **emergency = 0 misses**, **gating = 0 violations** (ledger-checked); `make eval-judged` adds Sonnet judge + Ragas (needs key/cassette).

---

## Critical source files (re-read at build time)
- `files/12_booking_api_spec.pdf` — 3 status enums, conditional nullability, channel auth, window bands.
- `files/01_*` + `02_service_area_*.pdf` — segmented ranges + gaps, Alexandria-pending, Loudoun, PG→EcoPower, 20742, 22046.
- `files/13_customer_messages.pdf` — gold; #3/22046 conflict, #5 Fri/Sat, #7 warranty, #17 clock.
- `files/07_cancellation_policy.pdf` — fee/waiver matrix + boundaries.
- `files/11_faq_emergencies.pdf` + `08_branch_hours.pdf` — 5 emergency categories + 1-800-555-0190 + hours.
- `files/03_hvac_pricing.pdf` + `06_warranty_terms.pdf` — Sunday/after-hours surcharge + `warranty_return ⇒ $0 diagnostic`.
