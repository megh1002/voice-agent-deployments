# Voice Agent Deployments

*A case study in deploying AI phone agents into real workflows, by Meghna Sarda.*

**Live demo: [voice-agent-deployments.up.railway.app](https://voice-agent-deployments.up.railway.app)**
(try a guided call; the first load may take a few seconds while the server wakes up)

I wanted to understand what it actually takes to deploy a voice agent into a real business workflow, not
just build the agent. So I worked through it the way a forward-deployed engineer would, for two simulated
customers: discovery first, then the client's rules written down, their systems connected, identity and
safety checks enforced in code, handoffs to staff designed, and every behavior tested before launch.

**This is not a product.** The customers and their systems are simulated, and all people and records are
synthetic. The point is the workflow thinking.

## The customers

| Customer | Industry | What the phone agent does | What stays with people |
|---|---|---|---|
| **Ravenswood Family Medicine** | Healthcare | Verifies identity, books, moves, and cancels appointments, offers freed slots to the waitlist | Symptoms, refills, test results, billing, and any red flag (with a structured handoff) |
| **Maple Court Apartments** | Property management | Triages after-hours maintenance calls by the building's rules and pages on-call for emergencies | The repair itself; anything not maintenance goes to the manager |

The clinic's discovery found that the client's request ("an AI receptionist") wasn't the need. The front
desk was answering phones and checking patients in at the same time, clinical calls reached the nurse
without the details she needed, and cancelled slots went unfilled. Read
[`customers/ravenswood_clinic/discovery.md`](customers/ravenswood_clinic/discovery.md).

## What I found

The full log is in [`FINDINGS.md`](FINDINGS.md), and every choice, with the alternatives, is in [`DECISIONS.md`](DECISIONS.md). Highlights:

- **Speech-to-text broke an identity check.** On a real voice test, "Damen Avenue" was heard as "Tamen
  Avenue," which would fail a correct caller's HIPAA verification. A text-only eval can never catch this.
  The fix: ask for the phone number first and read details back, spelling names. I deliberately did not
  accept fuzzy matches, because that would quietly weaken a privacy check.
- **A loose address match would have exposed a patient's record.** A test written for the fix above
  revealed that "4512 Anything Ave" matched the real address, because "Ave" counted as a street word.
- **Two emergencies need opposite instructions.** "Hang up and call 911" is right for chest pain and wrong
  for someone in crisis, who should stay on the line with 988 while staff join. Code refuses to end that call.
- **Evals need reviewing too.** A badly worded pass criterion would have failed a correct agent.

## How it's built

The model understands the caller and picks the right tool. Plain code applies the client's rules: who's
verified, what's urgent, what gets booked, who gets paged.

```
core/        the phone agent, assembled from workflow modules each customer switches on:
             red_flags · triage · identity · scheduling · handoff, plus guardrails on every reply
customers/   one pack per customer: discovery, playbook (their rules), adapter (their systems),
             a simulated backend, and test scenarios written before running
evals/       AI callers + code checks + an AI judge, with cost tracking
webapp/      the demo site: guided calls, a live staff view, findings, eval runs
tests/       39 checks that need no API key
```

- **Playbooks, not code, hold each client's rules.** Changing what counts as an emergency is a one-line edit.
- **The clinic's mock EHR uses FHIR's real data shapes** (Patient, Slot, Appointment, Task), with booking
  behind an adapter, because real EHRs often don't allow booking through FHIR.
- **Safety and privacy rules live in code**: the recording disclosure is played by code, the model never
  sees a patient record it isn't verified for, and a suicidal caller can't be hung up on.

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/pytest -q                                   # no API key needed
cp .env.example .env                                  # then add your Anthropic API key
.venv/bin/uvicorn webapp.app:app --port 8770          # http://localhost:8770
.venv/bin/python -m evals.run ravenswood_clinic       # full eval run (uses the API)
```

## Data

Every person, phone number, birth date, and record is fictional; phone numbers use the 555-01xx range
reserved for fiction. How real patient data would be handled (BAAs, access roles, minimum necessary,
retention, audit logs) is in decision D25 in [`DECISIONS.md`](DECISIONS.md).
