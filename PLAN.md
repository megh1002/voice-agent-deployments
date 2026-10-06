# Deploying voice agents into real workflows

## What this is

A reusable way to deploy an AI phone agent for a new business, shown with
simulated customers in different industries. The point is the **workflow
thinking** an FDE brings: find the real problem behind the request, decide what
to automate and what stays with people, write the client's rules down, connect
their systems, test before launch, and hand off well. It is not a product.

| Customer | Industry | Role in the project |
|---|---|---|
| **Ravenswood Family Medicine** | Healthcare | Headline: phone workflow redesign (identity, scheduling, handoffs, red flags) |
| **Logistics customer** | Logistics | Next: business-to-business calls, very different from patients |
| **Maple Court Apartments** | Property management | Extra example: after-hours triage and paging |

**Real:** the agent, the workflow code, text-message paging (outbox in testing), evals.
**Simulated:** the customers and their internal systems. All patient data is synthetic.

## How we work

- Claude Code builds. Meghna makes the decisions and logs them in `DECISIONS.md`.
- After each checkpoint, Meghna explains that part back in plain words.
- Ground claims in real sources. Anything unverified goes in the assumptions list.

## Layout

```
core/                    shared by every customer
  agent.py               the phone agent, assembled from the customer's workflows
  playbook.py            reads a customer's playbook (their rules)
  workflows/             one module per job the agent can do
    red_flags.py         safety situations: 911, or 988 + stay on the line
    triage.py            decide urgency, page on-call or create a ticket
    identity.py          verify who's calling (HIPAA); caller ID never counts
    scheduling.py        find, book, move, cancel; refill freed slots from the waitlist
    handoff.py           pass to the right staff queue with a structured summary
  guardrails.py          catches replies that claim things that didn't happen
  adapter.py             data shapes every customer's integration returns
  notifier.py            text messages: outbox (testing), shadow, or real SMS
  llm.py                 the one place that calls the Claude API
  budget.py              spend log + daily budget cap for the web app
evals/                   AI callers + code checks + AI judge -> runs/<customer>-<time>/
webapp/                  local web app: customers, try a call, staff view, eval runs
customers/
  ravenswood_clinic/     discovery, playbook, FHIR-shaped mock EHR, adapter, waitlist, 22 scenarios
  maple_court/           discovery, playbook, mock property system, adapter, on-call sheet, 24 scenarios
tests/                   33 checks that need no API key
```

## Phases

| # | Phase | Status |
|---|---|---|
| 1 | Shared core + Maple Court (first customer built) | ✅ |
| 2 | Core reshaped into workflow modules; "policy" renamed "playbook" | ✅ |
| 3 | Clinic: discovery, playbook, mock EHR, adapter, 21 scenarios | ✅ |
| 4 | Web app | ✅ |
| 5 | API key set up; first real test call ($0.07) | ✅ |
| 5a | Credit protection: spend log, daily cap, clear errors, cost meter | ✅ |
| 5b | Misheard names (F2/D23): phone first, read-back; fixed loose address check (F5) | ✅ |
| 5c | Visitor UI: guided calls, side panel, findings & decisions page, small screens | ✅ |
| 5d | **Full eval runs for both customers → fix → rerun** | next |
| ✅ | **Checkpoint A:** Meghna explains the clinic workflow and traces one call | |
| 6 | Voice layer: real phone number on the chosen platform (D2) | |
| 7 | Pilot: shadow mode, then live; Meghna makes 10–15 calls; call QA in the web app | |
| 8 | Logistics customer: discovery, playbook, adapter, scenarios. Time it | |
| ✅ | **Checkpoint B:** what carried over between industries and what didn't | |
| 9 | Write-up: README case study, product feedback memo, runbooks, demo video | |
| ✅ | **Checkpoint C:** 2-minute walkthrough out loud | |

## Running it

```bash
.venv/bin/pytest -q                                       # no API key needed
.venv/bin/uvicorn webapp.app:app --port 8770              # web app at http://localhost:8770
.venv/bin/python -m evals.run ravenswood_clinic           # needs the API key (see below)
```

The API key goes in a `.env` file (copy `.env.example`, fill in the key). It's gitignored, and Claude Code is set up so it can't read it.
