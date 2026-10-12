# Decisions

One entry per decision: what we chose, what else we considered, and why.
Entries marked *(proposed by Claude)* need Meghna's review: keep, change, or
reject, in her own words.

---

## D0. Shared core + several customers, not one property management project

- **Chose:** a reusable core for deploying voice agents, shown with two or more
  simulated customers in different industries.
- **Considered:** a single property management deployment; a standalone
  eval/monitoring/QA tool.
- **Why:** one industry makes readers in other industries do the translation.
  A standalone QA tool competes with funded products (Hamming, Coval, Cekura)
  and loses the customer-facing side of FDE work. A shared core plus customer
  packs shows both, and adds a finding no single deployment has: what carries
  over between industries.

## D14. Healthcare is the lead customer, logistics second

- **Chose (Meghna):** a healthcare clinic is the headline customer, logistics is
  customer 2. Maple Court stays in the repo as an extra example; it's already
  built and shows the core handles urgent safety calls.
- **Considered:** Maple Court as the lead; healthcare as customer 2.
- **Why:** almost anyone understands calling a doctor's office, so healthcare
  makes the voice AI idea clear to the most readers. It's also the biggest voice
  AI market. Logistics adds a business-to-business case that's very different
  from patients calling a clinic.

## D1. Test callers: AI callers and Meghna, each for a different job

- **Chose:** AI-simulated callers for the eval suite; Meghna makes 10–15 live
  calls for the pilot and demo.
- **Why:** AI callers are repeatable, so they work as regression tests. Live
  calls catch what AI callers miss: lag, interruptions, noise, rambling.

## D3. Model the mock system on Buildium *(proposed by Claude)*

- **Chose:** copy Buildium's data shapes in a small mock API. The on-call
  rotation lives in a separate spreadsheet.
- **Considered:** AppFolio or Yardi (partner-only APIs, no public docs); a plain
  spreadsheet as the whole system (no real integration).
- **Why:** Buildium's API docs are public. Splitting on-call into a spreadsheet
  copies a common real-world mess: the data the agent needs lives in two places.

## D4. Maple Court urgency levels *(proposed by Claude, needs sign-off)*

Four levels: **emergency** (page now) · **urgent** (first thing in the morning)
· **routine** (normal queue) · **redirect** (not maintenance).

| Gray-zone call | Proposed | Reasoning |
|---|---|---|
| No heat, has space heater (in season) | emergency | Heat Ordinance: space heaters don't count. Legal, not comfort |
| No hot water | urgent | RLTO essential service (24h clock), not dangerous overnight; morning fix meets the clock |
| Slow contained leak | urgent | Spreading water is a separate category (active_flooding) = emergency |
| Only toilet clogged, not overflowing | urgent | Real hardship, not dangerous; overflowing sewage = emergency |
| Fridge died | urgent | Food loss is real but not a safety issue |
| Power out, one unit (after breaker check) | urgent | Sparking or burning = electrical_hazard = emergency |
| Locked out | routine | Assumes the lease makes lockouts the tenant's cost (A7) |
| Unit door or front door won't lock | emergency | Security for one tenant or all 48 units |
| Window won't lock | urgent | Lower risk than a door |

## D8. The model picks a category; code decides what it means *(proposed by Claude)*

- **Chose:** the model only understands the caller and picks a category from the
  playbook. Plain code then decides the level, pages, creates tickets, and tells
  the model exactly what to say.
- **Considered:** letting the model judge urgency itself.
- **Why:** urgency is the client's rule, not the model's opinion. Code applies
  it the same way every time, can be tested without the AI, and can encode law
  exactly (heating season dates). If Dana changes a rule, it's a one-line edit.

## D9. The recording disclosure is played by code *(proposed by Claude)*

- **Why:** Illinois requires all-party consent. If the model wrote the greeting,
  it could skip or rephrase it. Code makes skipping it impossible.

## D10. Building-wide emergencies page once *(proposed by Claude)*

- **Chose:** if an emergency for a building-wide category (heat, water) is already
  open from the last 12 hours, later callers are told it's being handled, and
  nobody is paged again.
- **Why:** one boiler means 20 calls. Paging 20 times recreates the burnout the
  agent was meant to fix.

## D11. Text callers a dated confirmation *(proposed by Claude)*

- **Why:** RLTO deadlines start at notice, and the ordinance expects written
  notice. A dated text gives the tenant and the landlord the same record.

## D12. Eval design: expectations first, code checks carry the headline numbers *(proposed by Claude)*

- **Chose:** each scenario's expected level and paging are written from the
  playbook before any run. Code checks (level, paging, guardrails) produce the
  headline metrics. An AI judge grades only what needs reading (safety line
  first, tone, promises).
- **Why:** code checks are exact and free. AI judges can be wrong, so they
  shouldn't decide "did we miss an emergency."

## D20. "Playbook", not "policy"; separate from Aegis

- **Chose (Meghna):** this project shares no code or structure with Aegis. The
  client rules file is called `playbook.yaml`.
- **Why:** "policy" echoes Aegis's vocabulary. "Playbook" is also the word
  operations teams use for "how we handle X," which fits a workflow project.

## D21. The core is built from workflow modules *(proposed by Claude)*

- **Chose:** the agent is assembled from modules each customer switches on in its
  playbook: `red_flags`, `triage`, `identity`, `scheduling`, `handoff`. Each
  module brings its own instructions, tools, enforcement code, and guardrails.
- **Considered:** one agent with every tool; a separate agent per customer.
- **Why:** the clinic needed jobs Maple Court didn't (identity, booking,
  handoffs). Modules make "what carried over between industries" visible in
  the code: the agent loop, disclosure, guardrails, and evals carried over;
  triage is Maple Court's; identity, scheduling, and handoff came from the clinic.

## D16. Clinic integration: a mock EHR using FHIR's data shapes *(Claude's recommendation, accepted via "do everything")*

- **Why:** reliable and private. The public HAPI test server is shared and public,
  and its data can be wiped. Using FHIR's real resource shapes (Patient, Slot,
  Appointment, Task) keeps it honest, and booking sits behind the adapter
  because real EHRs often don't allow booking through FHIR.

## D17. Clinic v1 scope *(Claude's recommendation, accepted via "do everything")*

- **AI handles end to end:** book, reschedule, cancel, confirm, general questions,
  and waitlist backfill on cancellation.
- **Goes to people, with a structured summary:** symptoms and clinical
  questions, refills, test results, billing, records, new patients, anyone who
  asks for a person.

## D18. Suicidal caller: stay on the line *(Claude's recommendation, accepted via "do everything")*

- **Chose:** give 988, alert staff to join, keep the caller on the line. Code
  refuses `end_call` while this flag is active.
- **Why:** primary care guidance says not to disconnect. This is the opposite of
  the chest-pain instruction ("hang up and call 911"), which is why red flags
  carry their own `then:` rule. Needs physician sign-off in a real deployment.

## D19. Caregivers: only if on file *(Claude's recommendation, accepted via "do everything")*

- **Chose:** a caregiver can act for a patient only if listed as an authorized
  representative. Anyone else goes to the front desk.
- **Why:** HIPAA requires checking a representative's authority, not just
  knowing the patient's details. A spouse calling from a shared phone is the
  common case this blocks.

## D22. Caller ID is never used as identity at the clinic *(proposed by Claude)*

- **Why:** families share phones. Maple Court uses caller ID to greet tenants and
  find their unit (low risk). The clinic doesn't even show the model who the
  number belongs to, so it can't greet the wrong person by name.

## D23. Misheard names: phone first, read back, keep matching strict *(Claude's decision, delegated by Meghna)*

- **Chose:** ask for the phone number on file as the third identifier (address
  as fallback), and read details back, spelling names, before checking them.
  Both are playbook settings (`phone_first`, `read_back`).
- **Rejected:** accepting close matches ("Tamen" ≈ "Damen"). It's the easiest
  fix for callers, but it quietly weakens a HIPAA privacy check. Fix the caller
  experience; keep the security rule strict.
- **Later:** speech-to-text that can be given expected words (street names,
  clinicians, medications), in the voice-platform phase.

## D24. Credit protection *(Claude's decision)*

- Every API call's cost is logged (`runs/spend.jsonl`). The web app stops at a
  daily budget (`DAILY_BUDGET_USD`, default $1.00). Eval runs are logged but not
  capped, because you start them on purpose and the report shows the cost.
- API failures show a plain message ("credits have run out", "key rejected").
  A turn that failed before anything happened is rolled back so it can be retried.

## D25. Synthetic data on the public site, and how real data would be handled *(Claude's proposal, prompted by Meghna's question)*

- **On the site:** every person, phone number, birth date, and record is fictional.
  Phone numbers use the 555-01xx range reserved for fiction. Pages that show
  people's details are labeled, and the call page asks visitors not to type
  their own real details (anything typed is sent to the model provider).
- **Why show it at all:** visitors need the details to play the guided callers,
  and the staff view shows what staff really see in their own systems.
- **What changes with real patient data:**
  - Business Associate Agreements with every vendor that touches the data
    (phone carrier, speech-to-text, model provider, voice, hosting) before go-live.
  - Staff views behind a login, with roles: front desk, nurse, and billing see only their queues.
  - Minimum necessary: transcripts and logs store only what the workflow needs,
    and identifiers are removed from anything used for evals or analytics.
  - Retention limits on recordings and transcripts, set with the clinic's privacy officer.
  - An audit log of who viewed or changed which record, and when.
  - Evals keep running on synthetic data; real calls are reviewed only inside the clinic's systems.

## D26. Live calls are open to every visitor, no invite code (Meghna)

- **Chose:** anyone with the link can make live calls on the hosted demo.
- **Considered:** invite codes handed out with each link (built first, then removed).
- **Why:** less friction for the people she sends the link to.
- **What protects the API budget now:** a $1/day dollar cap on web-app spend
  (the real ceiling, about $30/month at most), 8 calls per visitor and 20 per
  network per day, and 20 turns per call. Visitor IDs are easy to reset, which is
  why the per-network limit exists.

## D27. The clinic agent is called Emma (Meghna)

- **Chose:** the clinic's agent introduces itself as "Emma, an AI assistant" (first named Ava, renamed to match the Vapi voice "Emma").
  Set in the playbook (`agent_name`), so each customer can choose.
- **Guardrail kept:** the greeting always says it's an AI, and if asked whether
  it's a person, it says plainly that it's an AI. A human-sounding name must
  never blur that, especially in healthcare.
- Maple Court's agent stays unnamed, which shows the choice is per client.

---

## Open

- **D2.** Voice platform: Vapi or Retell
- **D5.** Review the never-lists in both `playbook.yaml` files
- **D6.** Success targets (draft: 0 missed emergencies; unnecessary pages as low as possible)
- **D7.** Guardrails: flag bad replies (current) or block them before they're spoken?
- **D13.** Speed vs. quality: which model and effort level for live calls (latency matters on the phone)
