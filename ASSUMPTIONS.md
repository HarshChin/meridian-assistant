# Assumptions & Data Conflicts

Decisions made where the provided materials were ambiguous, contradictory, or
incomplete. Several of these are *conflicts inside the provided pack itself* — we
surface each one here (and again in the eval results summary) rather than papering
over it. Finding and handling them transparently is part of the deliverable.

## Conflicts found in the provided pack

1. **ZIP 22046 (test message #3) contradicts the North service-area policy.**
   `01_service_area_north.pdf` lists Fairfax coverage as `22030–22039, 22041–22044` and
   states *"ZIPs not listed above → escalate to Branch Manager for spot-approval."* 22046
   (Falls Church city) is **not** listed — so by the documented policy it should escalate,
   exactly like test #9 (Manassas 20110). Yet test #3's gold says *book it*. The same
   situation has opposite gold labels.
   **Decision:** we follow the **document**. The grounded coverage record contains only what
   the service-area docs state, so 22046 resolves to `unknown` → **escalate to the Branch
   Manager**, never silently booked on an inferred eligibility. (An earlier prototype carried a
   hand-authored branch-city `overrides.yaml`; it was removed when all facts moved to grounded
   extraction — hand-authoring a coverage fact the document does not state is exactly what the
   design forbids.) The unlisted-ZIP → `unknown` → **escalate** behavior is asserted directly by
   the coverage unit tests (`tests/unit/test_grounded_coverage.py`, which include 22046, the
   Fairfax/Arlington range gaps, Manassas 20110, and the South region). The conformance eval
   grades the **never-silently-book invariant** on out-of-area ZIPs (Loudoun 20147 → answer, no
   commit) and uses an in-range Fairfax ZIP (**22030**) for the unambiguous booking-success case.

2. **Test #5 says "Friday the 24th," but 2026-01-24 is a Saturday.** Source self-contradiction.
   We treat the **ISO date** as authoritative; relative phrases are resolved deterministically in
   code (never guessed by the LLM). The eval's reschedule case books the ISO date 2026-01-24 and
   asserts the API afternoon band (2:00–6:00 PM) in the reply; we do not assert the stated weekday.

3. **Appointment-window width.** `09_faq_booking.pdf` says appointments use "2-hour windows,"
   but `12_booking_api_spec.pdf`'s own example maps `afternoon → 14:00–18:00` (a 4-hour band).
   **Decision:** follow the **API spec** for booking math
   (`morning 07:00–11:00 / midday 11:00–14:00 / afternoon 14:00–18:00`). Customer-facing, we
   quote the API band and explain the day-of arrival window narrows.

4. **South region has branches but no coverage document.** `08_branch_hours.pdf` lists five
   South branches (Annapolis, Glen Burnie, Bowie, Laurel, Owings Mills), but no South
   service-area doc exists. **Decision:** any South/unmapped ZIP resolves to `unknown`
   (*distinct* from a documented `no`) → clarify/escalate. We do not invent coverage.

5. **Central region has no branch-assignment table** (unlike North, whose doc maps
   Fairfax/Arlington/Alexandria → Falls Church/Tysons and Loudoun → Herndon). **Decision:** the
   grounded extractor leaves Central counties' `primary_branch` **null** rather than inventing an
   assignment — the document does not state one, so neither do we. (Branch *operating hours* for
   all 11 locations, the Central branches included, are still compiled from `08_branch_hours.pdf`;
   only the county→branch *routing* for Central is absent and intentionally left unfilled. The UMD
   campus, ZIP 20742, still carries the documented facilities-coordination flag.)

## Engineering assumptions

6. **Channel mapping.** The provided messages label an inbound medium (Phone/Email); the API
   `channel` enum is `ivr | web_chat | email | agent`. We map Phone→`ivr`, Email→`email`,
   the CLI→`agent`, and the web demo→`web_chat`.

7. **Idempotency key.** Not part of `12_booking_api_spec.pdf`; we add a server-derived key to
   dedupe duplicate POSTs (and close the double-confirm race). Flagged as an added safety
   control, not a spec misread.

8. **Python 3.11 (not 3.12).** The plan targeted a 3.12 venv; 3.11 is the interpreter installed
   on the build machine and is fully supported by the entire stack. It satisfies the actual
   intent — avoid Python 3.14's bleeding-edge wheel gaps — so we standardise on 3.11.

9. **`confirmation_sent` is simulated.** No real SMS/email is dispatched; the mock returns the
   flag as the spec describes.

10. **Federal-holiday set is a documented stub.** `api_contract.py` enumerates the 2026 US
    federal holidays (the demo/eval window). The corpus references holidays for the surcharge but
    does not enumerate them, and they are not business facts that scale with the corpus, so they
    live in code as an acknowledged simplification. Production would compute them per year (e.g.
    the `holidays` package) keyed on the appointment's year.

11. **Holidays are modelled as open-with-surcharge, not closed.** The pricing docs add a +$125
    Sunday/holiday surcharge (implying service *is* offered then), so branch openness for
    `first_available` does not treat a federal holiday as a closure — a holiday slot may be offered
    with the holiday surcharge applied rather than skipped. (Sundays remain not-open for normal
    booking per the branch hours.)

12. **Emergency dispatch fees include the $89 HVAC figure.** `11_faq_emergencies.pdf` states
    *"Emergency dispatch fees ($99 plumbing, $89 HVAC)"*; both are compiled. The fee lives in the
    emergencies FAQ rather than the HVAC pricing sheet, so the fee extractor selects documents by
    relevance (not a fixed top-N) to capture it.

13. **Emergency detection is rules-first + an LLM paraphrase union, screened per message.** A
    recall-biased keyword set (code, doc-11 provenance) runs first; the safety node then adds an
    LLM paraphrase-catch that may only *add* an emergency, never veto one. The keyword set is
    recall-biased and covers common paraphrases (water spreading/pooling, ceiling leaks, a
    rotten-egg gas smell, a buzzing/hot breaker panel…), and the eval now measures **both** recall
    on paraphrased emergencies **and precision** against hard negatives (an under-performing AC on a
    mild day; a "family emergency at work" reschedule) so the recall bias doesn't silently
    over-escalate. We deliberately simplify the threshold-conditional triggers (no-heat below 40°F /
    no-cooling above 95°F) to phrase matches, and screen only the latest message (a hazard disclosed
    in an earlier turn is caught when stated, not re-screened on a later follow-up). For
    never-before-seen wordings the keyless path still leans on the keyword rules; the always-on LLM
    union (production, where a key is always present) is the durable recall backstop.

14. **Agent abstention is keyed on dense-cosine confidence.** The retriever fuses dense + BM25
    (RRF) for ranking, but the HIGH/MEDIUM/LOW abstention band uses the top dense cosine; a purely
    lexical match could under-score. Thresholds are tuned on a held-out probe; documented here as
    a deliberate, tunable choice rather than a bug.

15. **The agent's `TurnTrace` is checkpointed as a pydantic object via the in-memory saver.** The
    trace types are now **registered with the checkpoint serializer**, so a future strict-msgpack
    default is already handled; moving to a persistent checkpointer (SQLite/Postgres) for production
    is a config swap behind the same `thread_id` seam. Forward-compatibility note, not a defect.

16. **Each turn is classified in isolation — no multi-turn slot memory yet.** The session
    checkpointer (keyed by `thread_id`) carries the confirm-before-commit interrupt across turns,
    but the agent does **not** keep a conversation history or accumulate partial slots: the
    classifier sees only the latest message and `slots` are replaced (not merged) each turn. So a
    clarifying follow-up — "book HVAC" → "what's the ZIP?" → "22030" — does not continue the
    in-progress booking (the customer is expected to state a request in one message; the confirm
    round-trip itself *is* stateful). This is a deliberate prototype scope: the path-to-production
    is a per-session `messages` history + slot accumulation across clarify turns on a durable
    checkpointer — see `docs/path_to_production.md`.

17. **Booking ids are short and sequential (`BK-001`..`BK-009` seeded, `BK-101+` generated).** The
    doc-12 spec *example* shows an 8-digit id (`BK-00483921`), but the id is an arbitrary identifier,
    not a business rule, so we use short, readable ids (easy to read out / type on a call) and the
    booking-id matcher accepts `BK-` followed by any digits. Swapping the format is a one-line change
    and changes no behaviour.
