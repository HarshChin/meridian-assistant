# Path to Production — one page

This prototype is built so the path to production is mostly *promotion of components behind stable
interfaces*, not a rewrite. What follows is what changes, in priority order.

## 1. Multi-tenant, versioned knowledge (the core scaling story)
- Key the knowledge base by `(branch_id, doc_type, version)` with **branch → region → global**
  resolution, so a branch override falls back to a regional then a global policy. Retrieval and
  extraction become **tenant-scoped**; answers cite the **live version** they used.
- The compile-time extraction pipeline is unchanged — it already works on an arbitrary corpus with
  zero code changes. Production adds **freshness/version pinning** and an automatic flip of
  "pending Q2"-style effective-dated facts when their date arrives.
- The South-region "branches but no coverage document" gap becomes a **deploy-time config check**
  (fail the deploy, don't silently answer `unknown`).

## 2. Throughput & latency (~8,500 interactions/month, spiky)
- Async request handling + a worker pool; per-tenant rate limits; a queue with backpressure.
- **Emergency detection short-circuits sub-second** (rules run before any model call).
- Targets: p50 < 3s, p95 < 8s for knowledge answers. **Prompt caching** for the system/tool
  preambles; tenant- and version-scoped retrieval caches.

## 3. Hardening (security & correctness)
- Swap the mock Booking API for the real booking system **behind the same `BookingClient`
  interface** — the agent, tools, and eval don't change.
- **State & persistence.** The prototype's `BookingStore` is **in-memory** (bookings + the mutation
  ledger + idempotency keys + the no-show-waiver ledger), seeded fresh per process, so bookings are
  real and queryable *within a session* but do not survive a restart. Production swaps it for a
  **durable datastore** (e.g. Postgres) behind the same `BookingService`/`BookingClient` boundary:
  the mutation ledger becomes the **append-only audit log**, idempotency keys a **unique
  constraint**, the waiver ledger a per-customer table — with **no changes above the service
  layer**. The injected `Clock` likewise just switches from the frozen demo instant to the real
  wall clock (no `datetime.now()` is buried in business logic to untangle).
- **Multi-turn conversation memory.** The agent currently classifies each message **in isolation**:
  the session checkpointer carries the confirm-before-commit interrupt across turns, but *not* a
  conversation history or partial slots (the classifier sees only the latest message and `slots` are
  replaced, not merged, each turn). So a clarifying follow-up — "book HVAC" → "what's the ZIP?" →
  "22030" — restarts rather than continuing the in-progress booking. Production keeps a per-session
  `messages` history and **accumulates partial slots across clarify turns** (so the follow-up
  completes the booking), feeds recent context to the classifier, and runs on a **durable
  checkpointer** (Redis/Postgres) keyed by the existing session/`thread_id`. The seam is already
  there — LangGraph already checkpoints per `thread_id` (and resumes the confirmation interrupt that
  way); production deepens *what* is persisted. (The single-message confirm round-trip is already
  stateful; it is multi-turn slot-filling that this adds.)
- Scoped-token rotation + channel-scoped auth (already modelled); **server-side** enum/range/PII
  validation; an in/out **guardrail service** (emergency, injection, fee-no-waive, PII) as a shared
  dependency; idempotency keys on all mutations (already implemented) to close double-confirm races.
- A deterministic fallback when the LLM is unavailable: FAQ/callback/emergency-line routing rather
  than a hard failure. Auth on the serving API; the demo is intentionally unauthenticated.

## 4. Observability & evaluation in CI
- Promote `TurnTrace` to structured tracing (LangSmith / OpenTelemetry): retrieval-hit rate,
  groundedness/hallucination rate, **handoff rate + reasons**, containment, CSAT, latency, cost,
  drift.
- The **eval runs in CI as a gate**; the emergency-recall and confirmation-gating invariants are
  **hard, non-zero-exit** gates. Canary / A-B rollout with **auto-rollback** on safety-metric
  regression; a human-review queue is the real-world control behind every abstention.
- **Ragas (+ an LLM-judge tier) for answer quality at scale — added in production, not now.** Ragas
  ships as an optional, import-guarded `[ragas]` extra and is deliberately kept *out* of the core
  and the CI gate: a Ragas/LangChain transitive-dependency conflict must never be able to block the
  **keyless deterministic gate**, on which the prototype's correctness story rests (the deterministic
  tier + the categorical safety invariants need no extra dependencies and reproduce offline). In
  production it earns its place as a **continuous, directional** quality signal — Ragas
  **faithfulness / answer-relevancy / context-precision** over sampled live traffic, alongside a
  stronger-model groundedness judge — trended on the dashboards and alerted on drift, but **never a
  hard pass/fail gate** (those stay the deterministic safety invariants). It complements exact
  fact-match by catching unsupported-but-plausible answers that substring checks can't.
- **A living eval set fed by real misses.** Any live answer a customer (or a reviewing agent)
  flags as wrong is routed to the **human-review queue**; a reviewer confirms the failure and records
  the corrected expected behaviour, and that case — with its source citation and gold answer — is
  **added to the eval dataset**. Every real-world miss thus becomes a permanent regression test, so
  the suite grows toward the traffic the assistant actually sees and the same mistake can't silently
  return.

## 5. Infrastructure changes from the prototype
- Managed vector DB (pgvector / Qdrant) keeping the BM25 hybrid; an optional cross-encoder reranker
  (deliberately omitted today — a localized post-fusion step in `HybridRetriever.search`) once
  chunk-level metrics justify it.
- A KB CMS with version pinning and freshness SLAs; promote the static demo page to a real SPA only
  if/when the product warrants it.

## What stays exactly as-is
The compile-time/runtime split, the schema-is-the-API principle, deterministic booking-critical
logic, confirm-before-commit by topology, the keyless record/replay cache for reproducible evals,
and the document-agnostic ingestion + grounded extraction — these are the load-bearing design
choices and they are already production-shaped.
