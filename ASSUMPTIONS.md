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
   **Decision:** a labeled `data/service_area/overrides.yaml` records branch-city ZIPs
   (`source: inferred-from-branch-location (doc 08)`, `confidence: low`), consulted only
   *after* the documented ranges. The assistant may offer the booking **but must surface the
   low-confidence override** — it must never present an inferred eligibility as documented
   fact. The eval grades *that disclosure invariant*, not "a booking happened," and uses a
   genuinely in-range ZIP (**22032**) for the unambiguous booking-success case.

2. **Test #5 says "Friday the 24th," but 2026-01-24 is a Saturday.** Source self-contradiction.
   We treat the **ISO date** as authoritative and add a calendar-consistency assertion in the
   eval (`weekday(date) == stated_weekday`) that flags the mismatch instead of hiding it.

3. **Appointment-window width.** `09_faq_booking.pdf` says appointments use "2-hour windows,"
   but `12_booking_api_spec.pdf`'s own example maps `afternoon → 14:00–18:00` (a 4-hour band).
   **Decision:** follow the **API spec** for booking math
   (`morning 07:00–11:00 / midday 11:00–14:00 / afternoon 14:00–18:00`). Customer-facing, we
   quote the API band and explain the day-of arrival window narrows.

4. **South region has branches but no coverage document.** `08_branch_hours.pdf` lists five
   South branches (Annapolis, Glen Burnie, Bowie, Laurel, Owings Mills), but no South
   service-area doc exists. **Decision:** any South/unmapped ZIP resolves to `unknown`
   (*distinct* from a documented `no`) → clarify/escalate. We do not invent coverage.

5. **Central region has no branch-assignment table** (unlike North). **Decision:** a documented
   assumption derived from `08_branch_hours.pdf` (Rockville / Columbia / College Park; the
   University of Maryland campus, ZIP 20742, maps to College Park and carries a
   facilities-coordination flag).

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
