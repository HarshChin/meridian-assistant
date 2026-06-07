# Design Evolution & Debugging Log

An honest record of where the **first** approach was wrong, **why** it was wrong, **how** we
caught it, and the **more pragmatic approach** we replaced it with. This doubles as the
"debugging methodology" deliverable: it shows how the design was stress-tested rather than
assumed correct.

Each entry follows the same shape so it is easy to reason about:

> **First approach** → **Why it was wrong** → **How we found it** → **The fix** → **Status now**

---

## 0. How we caught our own mistakes (the methodology)

We did not trust "it runs" as evidence. Four independent checks found every issue below:

1. **Document-faithful verification, not just "no crash."** For coverage we asserted all
   **17 documented edges** (gaps, pending, sub-contracted, partner-referral, coordination,
   out-of-area) against the source docs — which is what surfaced the 15/17 → 17/17 miss (§3.2).
2. **End-to-end runtime smoke (48 checks).** Drives the *real* runtime (the mock `BookingService`
   over the in-process double + the HTTP layer + every knowledge function) as a caller would, and
   self-grades against the documents — not the unit-test harness.
3. **Adversarial verification (multi-agent).** A review fanned out across five dimensions
   (runtime regressions, extraction generalization, hardcoded-fact audit, determinism,
   smoke-expectation faithfulness); **every** finding was then independently re-verified against
   the code before we acted. It produced **24 raw findings → 10 confirmed**, including the two most
   important issues below (§3.3 and §3.5), which our own tests had *passed over*.
4. **The gate.** ruff + mypy + the full test suite (currently 150 tests), with the LLM cache
   committed so the agent *and* the grounded path **replay keyless** and reproduce offline.

The recurring lesson: **a test that encodes a wrong expectation hides the bug.** Two of our
tests asserted incomplete/old values and went green; only checking the *expectations against the
documents* exposed them (§3.5).

We ran this same loop at the end of **every** later phase — the LangGraph agent (P5), the eval
harness (P7, where we adversarially reviewed the *eval itself*), and the web demo (P8) — and then
again when **running the assistant as a real user** during demo prep. §5 records what that live use
surfaced: behaviours that passed the happy-path tests but failed on a realistic message.

---

## 1. Data & knowledge

### 1.1 Hand-authored YAML business facts → facts compiled from the documents
- **First approach.** Prices, fees, ZIP coverage, branch hours, and policy thresholds were
  hand-transcribed into `data/policy.yaml`, `data/service_area/*.yaml`, `data/branches.yaml`, each
  tagged with a source doc.
- **Why it was wrong.** It does not scale or generalize: with thousands of documents you cannot
  hand-maintain the YAML, and the system is silently biased to the 13 sample PDFs. It is also a
  second source of truth that can drift from the documents. The design is judged on sustainability,
  reproducibility, and generalization — hand-authored facts fail all three.
- **How we found it.** Direct review feedback ("when we have 10,000 documents how will we manually
  create policy.yaml? … it shouldn't be biased to just these 13 PDFs").
- **The fix.** A **knowledge-compilation pipeline** with one governing principle: *schema is the
  system's API (a small, finite set we hand-define); data is compiled from the documents.* An LLM
  extractor compiles each capability's values from the corpus into validated records under
  `data/extracted/*.json` at **compile time** (`make extract`); runtime loads those records. We
  hand-define only the *shape* of a fact (a fee has tiers; coverage has ZIP ranges) — which is set
  by what the assistant *does*, not by how many documents exist.
- **Status now.** All business YAML deleted. `coverage.json`, `fees.json`, `branches.json` +
  a provenance manifest are compiled from the docs and committed; the mock Booking API reads the
  same compiled `fees.json`. The only code constants left are the **doc-12 Booking-API contract**
  (window bands, max-advance, notes length) and a **documented federal-holiday stub** — implemented
  spec, not corpus facts.

### 1.2 ZIP 22046 hand-authored "override" → document-faithful escalation
- **First approach.** Test message #3 says "book Falls Church 22046", but doc 01 lists Fairfax as
  `22030–22039, 22041–22044` and says unlisted ZIPs escalate. To satisfy the gold label we added a
  low-confidence `overrides.yaml` (branch-city ZIP, inferred from doc 08).
- **Why it was wrong.** It hand-authors a coverage fact the document does not state — exactly what
  the design forbids — and the same situation (test #9, Manassas) has the opposite gold, so the
  "gold" is internally inconsistent.
- **How we found it.** Fell out of §1.1: once facts must come from documents, an inferred override
  has no place.
- **The fix.** Follow the document. 22046 is not in any documented segment → `unknown` →
  **escalate to the Branch Manager**, never silently booked. The eval grades the
  *disclosure/escalation invariant*, not "a booking happened", and uses an unambiguously in-range
  ZIP (`22032`) for the booking-success case.
- **Status now.** `overrides.yaml` deleted; behavior is document-faithful and covered by a test.
  Documented in `ASSUMPTIONS.md` #1.

---

## 2. Ingestion & parsing

### 2.1 Chunking: fixed-size → sliding-window → structure-aware
- **The ladder we worked through.** Chunking quality directly bounds both retrieval recall *and*
  grounded-extraction completeness, so we climbed the standard ladder, and each rung fixed a
  concrete failure of the one below:
  1. **Fixed-size** (split every N tokens/chars, no overlap) — the textbook baseline. Rejected on
     sight for this corpus: it slices mid-row and mid-list, so a coverage-table row or a fee tier is
     severed from its header/context and is cleanly retrievable from neither side.
  2. **Sliding-window** (fixed-size *with* overlap) — our **first implementation**. The overlap
     means a fact near a boundary appears whole in at least one window, which is strictly better
     than fixed-size. But it is still **structure-blind**: it splits a table from its header and a
     fee-tier list across windows, returns chunks that are half one section and half another, and
     pays for the safety with redundant overlapped text.
  3. **Structure-aware** (chunk on the document's real structure) — what we **shipped**.
- **Why sliding-window wasn't enough (how we found it).** Review feedback pushed for genuinely
  structure-aware chunking; inspecting the sliding-window output showed semantic units (a whole
  coverage table, a plan comparison, an FAQ Q&A) split across boundaries — the exact thing that
  later breaks retrieval recall and grounded extraction (see §3.2).
- **The fix.** Derive headings **generically from font size** (relative to the body-text mode, plus
  an "ends in ?" rule for FAQ questions), then chunk by section — keeping a whole table, plan
  comparison, or Q&A intact — and **keep sliding-window as the fallback** for any document that
  exposes no detectable structure. This is document-agnostic (no per-document rules), so it
  generalizes to an arbitrary corpus, and the lower rung survives as a graceful degradation rather
  than being discarded.
- **Status now.** 48 structure-aware chunks; tests assert tables/plans stay intact and FAQ Q&As
  split correctly. *(Interview point: each rung solved a real failure of the rung below, and we
  retained sliding-window as the fallback rather than betting the whole corpus is well-structured.)*

### 2.2 PyMuPDF vs pdfplumber, and the ✓/✗ glyph artifacts
- **First approach.** Considered PyMuPDF for parsing; the coverage tables use ✓/✗ marks.
- **Why it was wrong.** PyMuPDF dropped the ✓ glyph to blank **and** shattered table rows;
  pdfplumber keeps rows aligned but maps `✓→"3"` and `✗→"7"`. Either way the booking-critical
  coverage table is corrupted at the glyph level — and the tempting fix (a per-document "3 means
  yes" hack) would be brittle and non-generalizing.
- **How we found it.** Probed both libraries on the real PDFs and compared table fidelity.
- **The fix.** Stay on **pdfplumber** (better table-row fidelity, MIT-licensed) and handle the
  garbled marks where it generalizes: in the **extraction prompt** ("an affirmative mark may
  extract as 3/Y/P …; a negative as 7/N/blank; explicit words win"), not as a per-doc rule. Proven
  by a generalization test (§3.6).
- **Status now.** pdfplumber in `ingestion/`; glyph handling lives in the extractor prompt and is
  validated on unseen documents.

---

## 3. Extraction architecture (the part we iterated on most)

### 3.1 Runtime retrieve-then-extract → compile-time extraction + runtime load
- **First approach.** The first grounded resolver retrieved chunks and called the LLM to extract
  coverage **at runtime**, per query (cached).
- **Why it was wrong.** It puts retrieval + an LLM in the booking-critical path, so a retrieval
  glitch or a prompt change could alter *who we book* or *what we charge*, and runtime is slower and
  less deterministic.
- **How we found it.** Articulating the principle "a retrieval glitch must never change who we book"
  made the runtime LLM call indefensible.
- **The fix.** Split the two phases: extraction runs **offline at compile time** into committed,
  validated records; **runtime loads those records and applies deterministic logic** (ZIP-range
  membership, fee tiers) — no LLM or retrieval at transaction time.
- **Status now.** `extraction/` (compile-time) vs `knowledge/` (runtime loaders + deterministic
  logic) are cleanly separated; the booking-critical path is keyless and deterministic.

### 3.2 Section-cropped extraction → parent-document (full-document) extraction
- **First approach.** Extract from the top-k retrieved **chunks**.
- **Why it was wrong.** A fact can live in a section that doesn't rank in the top-k. The central
  region's *"Important Notes"* chunk (EcoPower electrical referral + UMD 20742 coordination) ranked
  below the top-8, so those flags were dropped — coverage came out **15/17** on the documented edges.
- **How we found it.** The 17-edge verification flagged exactly the two missing flags; a retrieval
  trace confirmed the notes chunk was below the cut.
- **The fix.** A **parent-document** pattern: rank *documents* by their retrieved chunks, then
  extract from each document's **full text** — so a fact in any section is never cropped out.
- **Status now.** **17/17** documented edges; the principle generalizes (don't crop; give the
  extractor the whole relevant document).

### 3.3 Fixed top-N document selection → relative, score-gated selection  *(found by adversarial review)*
- **First approach.** `_gather_top_docs(query, n_docs=2)` — extract from the 2 highest-ranked docs.
- **Why it was wrong.** `2` was silently tuned to *exactly* the two sample service-area docs. Add a
  third region (the repo already ships a SOUTH region with five branches) and the 3rd document is
  dropped → every county in it becomes absent from `coverage.json` → a fully serviceable ZIP is
  mis-classified as `unknown`/out-of-area. A hard-coded count is the special-casing the design
  forbids, and the failure is silent and safety-relevant.
- **How we found it.** The adversarial verification's "generalization" dimension; re-verified by
  reading the code path end to end.
- **The fix.** Selection is now **relative, never a fixed count**: keep a document if its aggregated
  chunk relevance is within a ratio of the most-relevant document **or** it has a chunk strongly
  on-topic. The number of documents extracted **scales with how many are genuinely relevant** — no
  per-corpus constant — with a high safety cap that *logs* (never silently truncates).
- **Status now.** Implemented in `extraction/extractors.py`; coverage/branches/fees all use it.

### 3.4 One broad fee query → per-concept / per-entity targeted extraction
- **First approach.** A single `FeeSchedule` extraction from the top-N fee-ish documents.
- **Why it was wrong.** Fee facts are spread across four documents (cancellation + three pricing
  sheets). One broad query (a) let two FAQ docs out-rank `electrical_pricing`, dropping the
  electrical diagnostic fee, and (b) let the model mis-file HVAC's `$89` as an emergency-dispatch
  fee. A later "core fees" combined query then returned `<UNKNOWN>` for surcharge fields because the
  cancellation doc dominated and pushed `hvac_pricing` (which holds the surcharge) below the cut.
- **How we found it.** Inspecting the compiled `fees.json` after each compile against the documents.
- **The fix.** Decompose by concept, each from its **own targeted retrieval**: cancellation,
  surcharge, **per-line** diagnostic (iterating the known `ServiceType` values), and emergency
  dispatch — so completeness never depends on several differently-relevant documents all surfacing
  in one top-N. (This is the same per-entity pattern the design advertises as "what scales to many
  documents", now applied consistently rather than only to fees.)
- **Status now.** `fees.json` correct and complete: diagnostic `{hvac:89, plumbing:75,
  electrical:85}`, cancellation/surcharge thresholds all right.

### 3.5 Missing `$89` HVAC emergency-dispatch fee → dual-criterion cross-document capture  *(found by adversarial review)*
- **First approach.** Extract each line's emergency-dispatch fee from that line's pricing query.
- **Why it was wrong.** The `$89` HVAC emergency-dispatch fee is stated only in
  `faq_emergencies.pdf` ("Emergency dispatch fees ($99 plumbing, $89 HVAC)") — a **different**
  document than the HVAC pricing sheet. Both the original hand-authored YAML *and* our first
  extraction dropped it. Worse, two of our tests **asserted the incomplete value and passed** —
  the bug was hidden by its own expectations.
- **How we found it.** The adversarial "smoke-faithfulness" dimension checked our expectations
  against the source docs and found the `$89` figure we had omitted.
- **The fix.** Extract emergency-dispatch fees as their own **cross-line** extraction (they are
  stated together), and make document selection **dual-criterion**: a document is kept if its
  aggregate relevance clears the ratio **or** it has a strongly on-topic chunk. The FAQ's
  emergency-dispatch line is a strong-but-singular match that a higher-volume pricing doc was
  masking; the cosine criterion now catches it. Thresholds were calibrated empirically (the
  needed doc scores ~0.84 vs a noise ceiling ~0.73).
- **Status now.** `emergency_dispatch_fees_usd = {plumbing:99, hvac:89}` — the grounded path is
  strictly **more complete** than the hand-authored data it replaced; tests + `ASSUMPTIONS.md` #12
  updated to the document-faithful value.

### 3.6 Glyph prompt keyed to the sample's `3`/`7` → generalized + a second-encoding proof  *(found by adversarial review)*
- **First approach.** The prompt mapped the sample's specific artifacts (`✓→"3"`, `✗→"7"`), and the
  generalization test reused that same encoding.
- **Why it was wrong.** It proved generalization only to documents from the *same* PDF toolchain; a
  different toolchain (checkmarks as `Y`, blanks, `X`) wouldn't be covered, and the test couldn't
  catch that because it used `3`/`7` too.
- **How we found it.** The adversarial "generalization" dimension flagged the prompt as
  sample-tuned and the test as self-reinforcing.
- **The fix.** Generalize the prompt to affirmative/negative *marks* (3/Y/P… vs 7/N/blank) with
  **explicit words always winning**, and add a **second** generalization fixture using a different
  layout (pipe-delimited) and **word-based** availability (Yes/No/Pending/Sub-contracted) with a
  different partner name. Both unseen documents compile correctly through the unchanged extractor.
- **Status now.** 9 generalization assertions across **two** encodings, all green.

---

## 4. Robustness & reproducibility  *(all found by adversarial review)*

### 4.1 `max_tokens` could silently truncate → raise loudly
- **First approach.** A fixed `max_tokens=4096` for every structured call, with no check on the
  response.
- **Why it was wrong.** A large extraction (many counties/branches) could hit the cap and return a
  **truncated** tool call, which would either crash validation or — worse — cache a partial record
  as canonical.
- **The fix.** Detect `stop_reason == "max_tokens"` and **raise** (never cache a partial record);
  raise the cap to 8192. A truncation is now a loud, actionable failure ("shard the extraction"),
  not silent data loss.
- **Status now.** Guard in `llm/client.py`.

### 4.2 Non-reproducible manifest → deterministic provenance
- **First approach.** The compile step stamped the manifest with a `compiled_at` date passed on the
  command line.
- **Why it was wrong.** The committed manifest held a hand-typed date, but `make extract` (no arg)
  wrote `"unspecified"`, so re-running the documented command did **not** reproduce the manifest
  byte-for-byte — and the build's docstring claims it never reads the wall clock.
- **The fix.** Drop the wall-clock field entirely; provenance is now `model` + `corpus_hash` +
  per-capability source docs — all deterministic — so `make extract` reproduces every artifact,
  manifest included, byte-for-byte.
- **Status now.** Deterministic manifest; verified by re-compiling (records unchanged).

### 4.3 Loader caches with no invalidation hook → `reset_caches()`
- **First approach.** The runtime loaders are `lru_cache`d with no way to clear them.
- **Why it was wrong.** A latent testability footgun: a test or tool that repoints the data
  directory after first load would serve stale records.
- **The fix.** Added `knowledge.loader.reset_caches()` to clear all three loaders.
- **Status now.** Minor, but closed.

---

## 5. Agent, eval & demo (P5–P9) — hardened against live use

These surfaced after the extraction work, once the LangGraph agent, eval harness, and web demo
existed and we drove the assistant as a *customer* would. The pattern from §0 repeats: a behaviour
that "worked" on the happy path failed on a realistic message, and a thin test/eval expectation hid
it. (Earlier phases also fixed two agent-internal issues caught the same way: the `TurnTrace` was
silently dropped across the confirm interrupt until each node re-emitted it for the checkpoint, and
LangGraph warned on deserialising the trace until we registered its type with the checkpoint serde.)

### 5.1 An eval that could pass while broken → categorical, ledger-proven, fail-loud  *(found by adversarial review of the eval itself)*
- **First approach.** The P7 harness asserted intent / route / citations + the two safety invariants.
- **Why it was wrong.** Reviewing the *eval* adversarially (not just the agent) found four ways it
  could go green while broken: the lone status assertion `["12"]` was satisfied by the appointment
  window (`**12**:00 PM`) and the date, not just the 12-minute ETA it claimed to check (at the time
  the seed ids were 8-digit, so `BK-005**12**883` matched too — doubly vacuous);
  confirmation-gating was **opt-in per case**, so a new booking case that forgot a flag was invisible
  to the gate; the emergency *"never book"* half read the agent's **self-reported** trace flag
  (fail-open) instead of the mutation ledger; and the whole gate **skipped to green** if the
  committed index/cache were absent.
- **How we found it.** A 5-dimension adversarial review of the harness: **19 raised → 12 confirmed**.
- **The fix.** "Never book" is now proven against the **mutation ledger** (unconditional for every
  emergency case); gating is derived from the **mutating surface** (any book/reschedule/cancel case),
  not an opt-in flag; missing artifacts now **fail** the build instead of skipping; assertion-free
  cases fail; and a new `forbid_contains` grades that withheld PII is never leaked.
- **Status now.** Categorical, ledger-proven, fail-loud; 20/20, keyless.

### 5.2 "No technician assigned" for a withheld field → withheld-vs-absent
- **First approach.** `booking_status` reported "the technician/ETA only if present in the facts".
- **Why it was wrong.** The PII gate withholds the technician name (owner-only) when no matching
  `customer_id` is given; the model read the resulting `null` as *"a technician hasn't been assigned
  yet"* and fabricated a confident, wrong explanation for withheld data.
- **How we found it.** Live demo: "status of BK-…, when and who?" with no customer id.
- **The fix.** The lookup node distinguishes **withheld-pending-verification** from **absent**: the
  reply states what it can (status/date/window), explains the technician needs the customer id, and
  asks for it; with the id it returns the name. Graded by eval `st2`/`st3` (incl. *must-not-leak*).
- **Status now.** The PII gate reads as a feature, not a bug.

### 5.3 Date resolution: relative-only → absolute dates + a clear out-of-window message
- **First approach.** `resolve_relative_date` handled ISO, today/tomorrow, weekday names, "the Nth".
- **Why it was wrong.** Real customers type **absolute** dates ("12th jan 2026", "January 28"); those
  weren't parsed, so a fully-specified booking stalled in `clarify` — and the clarify LLM, seeing a
  date *had* been given, went off-script and asked about the "issue" instead of the date.
- **How we found it.** Live demo.
- **The fix.** Parse explicit month-name dates (unambiguous because a month *name* is present; numeric
  `1/12/2026` stays a clarify); a date outside the 60-day horizon now returns a clear "we book from X
  to Y" message rather than a confusing question or a commit-time failure; the clarify prompt is
  tightened to ask *exactly* for the missing piece. Covered by unit tests + eval `b3`.
- **Status now.** Absolute, relative, and out-of-window dates all handled deterministically.

### 5.4 Booking required a `customer_id` → capture contact details
- **First approach.** The classifier extracted booking slots but not the customer's contact info.
- **Why it was wrong.** A customer who gave a name/phone/email (but no account id) still couldn't be
  booked — the create contract needs *id-or-contact*, and contact was never captured, so the turn
  hit a dead end after they'd already provided their details.
- **How we found it.** Live demo.
- **The fix.** A dedicated contact extraction runs **only on the book-without-id path** (so the
  proven classify caches stay valid); `plan_booking` passes `customer_info` to `create_booking` and
  asks for identity only when **neither** an id nor contact details are present. Graded by `b3`.
- **Status now.** Books either from a `customer_id` or from supplied contact details.

### 5.5 Greetings handed off to a human → a `general` conversational lane
- **First approach.** Intents were knowledge_qa / book / reschedule / cancel / booking_status /
  out_of_scope, so a greeting like "hi" fell to `out_of_scope` → **human handoff** ("let me connect
  you with a specialist"), and the recall-biased emergency screen could occasionally false-positive
  on a 2-character input.
- **Why it was wrong.** A greeting should get a warm in-role reply — not a handoff, and never an
  emergency.
- **How we found it.** Live demo.
- **The fix.** A `general` intent + node answers greetings/chitchat conversationally; the classifier
  separates `general` (greetings, "what can you do?") from `out_of_scope` (off-topic *requests* like
  the weather); the emergency screen is hardened to never flag benign input (real-emergency recall is
  unaffected — the keyword rules fire first). Graded by eval `gen1`.
- **Status now.** Conversational opener; 0 emergency misses still holds.

### 5.6 One frozen clock everywhere → a clock-relative seed (eval pinned, demo current)
- **First approach.** A single canonical frozen instant (2026-01-20) used everywhere, with seed
  bookings hard-dated to January.
- **Why it was wrong.** A frozen clock makes "today" a *fixed* date (great for reproducibility, but
  surprising in a live demo), and hard-dated January fixtures look stale under any other clock (a
  January en-route job under a May "now"). There is no single seed date coherent at two different
  clocks.
- **How we found it.** Demo prep — wanting the demo to feel current without breaking the eval.
- **The fix.** Keep the **eval** pinned at the canonical instant (deterministic, keyless), but give
  the **demo** its own frozen instant (2026-05-01) and date the seed **relative to whichever clock is
  used**. The same fixtures reproduce the original January dates at the canonical clock (eval + cache
  untouched, byte-identical) and yield coherent May dates for the demo; `--system-clock` is coherent
  too. A frozen clock is a deliberate, fixed instant — "today" resolves to it, not the wall date.
- **Status now.** Eval untouched + keyless; demo coherent at 2026-05-01 (bookable May 1 – June 30).

### 5.7 Emergency recall only proven on literal triggers → paraphrase recall + a precision floor
- **First approach.** The emergency suite asserted recall only on *explicit* triggers ("burning
  smell from my electrical panel"), and there were no hard negatives.
- **Why it was wrong.** A "0 misses" recall claim over only literal phrasings doesn't show the screen
  catches **paraphrases** ("water spreading across the floor", "rotten eggs near the furnace", "a
  buzzing, hot breaker panel"), and a purely recall-biased screen with no precision test could
  silently over-escalate benign messages — eroding trust and burning the human queue.
- **How we found it.** Probing "what about unseen/paraphrased questions?" against the recorded eval.
- **The fix.** Broadened the recall-biased keyword rules to catch those common paraphrases at the
  rule level (so they're caught **keyless**, not only by the LLM union), and added an eval mini-suite:
  3 paraphrased positives (now rule-caught) **and** 2 hard negatives (an under-performing AC on a mild
  day; a "family emergency at work" reschedule) scored for **precision** — a false positive fails the
  case, but is kept out of the categorical *recall* counter (over-escalating is a UX/cost issue, not a
  missed emergency). The honest residual: a truly novel wording, run keyless, still relies on the
  rules; the always-on LLM union (production) is the durable backstop, and confirmed live misses feed
  the eval (§4 of `path_to_production.md`).
- **Status now.** Emergency recall **0 misses / 6** (3 literal + 3 paraphrase) and 2 hard negatives
  not over-flagged; the rule broadening regressed nothing (suite still green).

---

## 6. Alternatives we considered and deliberately did *not* adopt (right-sizing)

These are **not flaws** — they are choices where the obvious heavier option was rejected for a
pragmatic one. Included because an interviewer is likely to probe "why didn't you use X?". Marked
**[built]** (in the repo today) vs **[planned]** (a later phase, decision already made).

- **Embeddings — task-type / API embeddings → local `bge-base` with query/document prefixing.**
  **[built]** Considered Nomic-v1.5 task embeddings and Gemini/Voyage API embeddings; rejected
  because the gain is marginal on a ~50-chunk, lexically-distinctive corpus and API variants break
  the offline/reproducible/keyless guarantee. bge-base's asymmetric query/doc prefixing is already
  task-aware-for-retrieval and runs locally via ONNX.
- **Retrieval — hybrid BM25 + dense, fused with RRF (k≈15, not the web-scale 60).** **[built]**
  Digits/ZIPs/prices need lexical; prose needs semantic. RRF k is tuned for a small corpus; the
  principle is "ship the simpler single leg if fusion doesn't beat it at recall."
- **Vector store — Chroma (HNSW) default, with a NumPy exact backend + a parity test.** **[built]**
  HNSW (ANN) is over-spec'd at ~48 chunks (ANN targets 10⁵⁺), so it returns effectively-exact
  top-k here. We keep it for the persistence/metadata/scale story and turn the over-spec into a
  *validation artifact*: a test asserts HNSW top-k == exact top-k, with a `chunk_id` tie-break for
  determinism.
- **Reranker — none by default.** **[built: omitted]** A cross-encoder reranker is overkill at this
  scale; the chunk-level retrieval metrics decide, and it can be added later if a precision gap
  appears. We did not add a no-op hook we couldn't test.
- **Abstention — calibrated thresholds, not a fixed cutoff.** **[built]** Dense-cosine
  HIGH/MEDIUM/LOW bands (τ tuned empirically on real in- vs off-corpus cosines) so the assistant
  hands off rather than guesses when the corpus likely can't answer.
- **Eval — Ragas demoted from the harness to an optional, import-guarded extra.** **[built, P7]**
  Initially a core dependency; demoted to an optional `[ragas]` extra so a Ragas/LangChain install
  conflict can never block the keyless CI gate. The deterministic tier is the gate; Ragas, if ever
  wired, is a directional cross-check, never headline.
- **LLM judge — a *stronger, different* model judges, not the generator.** **[scaffolded, P7]** The
  design (a stronger, different model avoids same-model self-preference bias; cached judge samples so
  the judged tier reproduces offline) is decided, but the judged tier is **scaffolded, not yet
  implemented** — `make eval-judged` currently runs the deterministic tier and says so. The docs were
  corrected to stop advertising it as working (a doc-vs-code honesty fix from the P8/P9 review).
- **Interface — Streamlit → React/Vite SPA → minimal static HTML.** **[built, P8]** Streamlit first;
  considered a full SPA; shipped a vanilla static page (no build step) over a thin FastAPI shell that
  reuses the *same* `AgentRunner` as the CLI, so the browser exercises the identical
  confirm-before-commit path with near-zero clone-time risk. All server-supplied text is rendered as
  `textContent` (XSS-safe). The CLI is the canonical, testable interface; the web demo is non-blocking.
- **Booking statuses — three disjoint enums, not one union.** **[built]** The spec's create/lookup/
  modify status vocabularies are disjoint; modelling them as separate enums makes illegal states
  (e.g. `rescheduled` on a create response) unrepresentable rather than merely discouraged.
- **Time — an injected `Clock`, never `datetime.now()` in logic.** **[built]** Fees/windows are
  time-dependent; injecting a frozen clock makes every boundary case deterministic and testable.
- **Runtime — Python 3.12 (planned) → 3.11 (used).** **[built]** 3.11 is the installed interpreter,
  fully supported, and satisfies the real intent (avoid Python 3.14's bleeding-edge wheel gaps).
  See `ASSUMPTIONS.md` #8.
- **Portability — `zoneinfo` needed `tzdata` on Windows.** **[built]** Hit `ZoneInfoNotFoundError`
  on Windows; fixed by pinning the `tzdata` package rather than hand-rolling timezone offsets.

## Where we stand now

- **No hand-authored business facts anywhere.** Coverage, fees, and branch hours are compiled from
  the documents into committed, validated records; the assistant and the mock Booking API both read
  them. The only code constants are the doc-12 API contract and a documented holiday stub.
- **Booking-critical path is deterministic and keyless** — load compiled records + deterministic
  logic; no LLM or retrieval at transaction time.
- **Generalization is demonstrated, not asserted** — two unseen synthetic documents, in two
  different encodings, compile correctly through the unchanged extractor; document selection scales
  with relevance rather than a fixed count.
- **Reproducible** — temperature-0 LLM calls (extraction *and* the agent) with a committed cache
  replay offline; the compile step and manifest are deterministic. Verified end-to-end: with the API
  key removed, the full suite *and* the eval pass with zero errors.
- **Agent, eval & demo built (P5–P9)** — LangGraph agent with confirm-before-commit by topology; a
  categorical, ledger-proven eval (emergency recall + confirmation-gating as hard gates that *fail*,
  never skip, when inputs are missing); a CLI and a minimal static web demo reusing the same runner.
- **Gate green** — ruff + mypy clean; **150 tests** pass; **eval 20/20** (emergency 0/3, gating 0/9,
  retrieval recall@5 100%); generalization proven on two unseen encodings.

These are recorded honestly because the most defensible answer to "what did you get wrong?" is a
precise account of what we found and how we fixed it — most of it caught by our own verification
(including adversarially reviewing our own eval) rather than discovered in someone else's review.
