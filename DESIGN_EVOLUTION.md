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
4. **The gate.** ruff + mypy + the full test suite (currently 88 tests), with the LLM extraction
   cache committed so the grounded path **replays keyless** and reproduces offline.

The recurring lesson: **a test that encodes a wrong expectation hides the bug.** Two of our
tests asserted incomplete/old values and went green; only checking the *expectations against the
documents* exposed them (§3.5).

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

### 2.1 Sliding-window chunking → structure-aware chunking
- **First approach.** Fixed-size sliding-window chunks over the extracted text.
- **Why it was wrong.** It split semantic units that must stay whole for correct retrieval and
  extraction — a fee-tier list, a coverage table, or an FAQ Q&A cut across two chunks retrieves
  partially and answers wrongly.
- **How we found it.** Review feedback to use genuinely structure-aware chunking.
- **The fix.** Derive headings generically from **font size** (relative to the body-text mode, plus
  a "ends in ?" rule for FAQ questions), then chunk by section — keeping a whole table, plan
  comparison, or Q&A as one chunk, with a sliding-window fallback only when a document has no
  detectable structure. This is document-agnostic (no per-doc rules).
- **Status now.** 48 structure-aware chunks; tests assert tables/plans stay intact and FAQ Q&As
  split correctly.

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

## Where we stand now

- **No hand-authored business facts anywhere.** Coverage, fees, and branch hours are compiled from
  the documents into committed, validated records; the assistant and the mock Booking API both read
  them. The only code constants are the doc-12 API contract and a documented holiday stub.
- **Booking-critical path is deterministic and keyless** — load compiled records + deterministic
  logic; no LLM or retrieval at transaction time.
- **Generalization is demonstrated, not asserted** — two unseen synthetic documents, in two
  different encodings, compile correctly through the unchanged extractor; document selection scales
  with relevance rather than a fixed count.
- **Reproducible** — temperature-0 extraction with a committed cache (10 live entries) replays
  offline; the compile step and manifest are deterministic.
- **Gate green** — ruff + mypy clean; 88 tests pass (17 coverage edges, compiled fee/branch values,
  9 generalization assertions across two encodings); end-to-end runtime smoke green.

These are recorded honestly because the most defensible answer to "what did you get wrong?" is a
precise account of what we found and how we fixed it — most of it caught by our own
verification rather than discovered in review.
