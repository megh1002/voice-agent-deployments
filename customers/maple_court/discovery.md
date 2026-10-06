# 01 · Discovery

> **Simulated client.** Maple Court Apartments and its staff are fictional. Everything
> about the law, the industry, and the vendors comes from the public sources linked at
> the bottom. Vendor marketing claims are labeled as such.

---

## 1. The client

**Maple Court Apartments**, Rogers Park, Chicago
- 48 units, a 1920s courtyard building. **Steam radiator heat from one central boiler**,
  which is typical for older Chicago buildings.
- **Dana**, the property manager, runs the office 9–5 on weekdays.
- **Luis and Priya**, the two maintenance techs, swap on-call duty each week.

**How after-hours calls work today:** an answering service picks up and texts the
on-call tech whenever the tenant says something is urgent. The service doesn't judge
urgency itself. It passes along whatever the tenant says.

**What Dana says the problem is (simulated):** "My techs are getting woken up for
dripping faucets. Priya told me she'll quit if on-call doesn't get better. But I can't
miss a real emergency either. I'm the one who gets sued."

---

## 2. Who's involved and what each wants

| Person | Wants | Afraid of |
|---|---|---|
| **Tenant** | Someone to take the problem seriously, *tonight* | Being ignored; damage to their belongings; being cold |
| **On-call tech** (Luis / Priya) | Sleep. Get woken only for real emergencies | 2am calls for faucets; burnout |
| **Property manager** (Dana) | Keep the techs, keep tenants happy, stay legal | A missed emergency → damage, lawsuit, city violation |
| **Owner** | Low cost, no liability | Water damage spreading to other units; turnover costs |

**The core tension:** the tenant and the tech want opposite things from the same
rule. Dana is the one who sets the rule, so *the line between "page now" and "it can
wait" is her policy decision, not the agent's.* The agent should apply her rules
consistently. It shouldn't invent its own.

---

## 3. What the law says (the rules we can't negotiate)

### Chicago Heat Ordinance
- **Heating season is Sept 15 – June 1.**
- For radiator buildings like Maple Court: at least **68°F from 8:30am to 10:30pm**
  and **66°F from 10:30pm to 8:30am**.
- Space heaters and ovens **don't count** as the required heat source.

**What this means for us:** losing heat during heating season is a *legal* problem,
not just discomfort. A tenant saying "I have a space heater, so it's fine" doesn't
change the landlord's obligation.

### Chicago RLTO (Residential Landlord and Tenant Ordinance): essential services
- Essential services are **heat, running water, hot water, electricity, gas, plumbing.**
- If one fails, the tenant can (among other options) **withhold rent starting 24 hours
  after giving notice**, or **terminate the lease 72 hours after notice**.
- The ordinance expects notice **in writing**.

**What this means for us:** the timer starts when the landlord is notified, so the
after-hours call log is effectively a *legal record*. Sending the tenant a written
confirmation (a text message) after the call could matter to Dana as much as the
call itself. ⚠️ Whether a phone call to an AI agent counts as "notice" is unclear.
See the assumptions list.

### Illinois Eavesdropping Act
- Illinois requires **consent from everyone on the call** to record it. Recording
  without consent is a felony.

**What this means for us:** the agent says at the start of every call that it's an
AI assistant and that the call is recorded.

### Gas leaks (Peoples Gas safety guidance)
- If you smell gas: **leave the building immediately. Don't use phones, light
  switches, or anything electrical inside.** Call Peoples Gas (866-556-6002) and 911
  from outside.

**What this means for us:** a tenant reporting gas is *on the phone*, possibly
*inside*. The agent's first job isn't collecting details for a work order. It's to
tell them to get out and call from outside. **Some emergencies belong to 911 or the
utility first and maintenance second.**

---

## 4. How the industry handles this today

- **Answering services** sort after-hours calls using each client's own rules.
  Typical "true emergencies" are flooding, gas smells, and loss of heat. Everything
  else gets logged for the next business day.
- **On-call burnout is a known retention problem.** Industry articles describe
  maintenance coordinators quitting over constant late-night calls that turn out not
  to be emergencies. One widely cited figure puts maintenance staff turnover at 39.2%.
- **Vendor claims (marketing, not verified):**
  - "Over 90% of after-hours calls are not emergencies."
  - Property Meld says its AI on-call product finds that 40% of issues reported as
    emergencies aren't.
- **AI products already do this:** Property Meld (MAX On-Call), Thoughtly, Phonely,
  and others. This project doesn't try to beat them. It's about understanding
  what deploying one well takes.
- **The real property management software** stores maintenance as "tasks" and "work
  orders." Buildium's public API is one example, with fields like title, category,
  description, priority, status, unit, and assigned person. Our mock system will copy
  that shape.

---

## 5. Types of calls (draft)

### Clearly emergencies: act now
| Call | First action |
|---|---|
| Smell gas | **Safety first:** get out, call Peoples Gas + 911 from outside. Then page the tech. |
| Fire, smoke, carbon monoxide alarm going off | **911 first.** Then page the tech. |
| Active flooding / burst pipe / water coming through ceiling | Page now. Tell them where the water shutoff is if known. |
| No heat in heating season | Page now. It's a legal requirement. |
| Sewage backing up | Page now. |
| Someone stuck in the elevator | **911 first.** (Maple Court has no elevator, but this is worth noting for other buildings.) |

### Clearly routine: log for the morning
Dripping faucet, running toilet, one light out, a cabinet door broken, appliance
noise, pest sighting, a request for a new key.

### The gray zone: **this is the decision you'll make (D4)**
| Call | Why it's hard |
|---|---|
| No heat, but "I have a space heater" | Comfort says wait. The law says it's a violation. |
| No hot water | An essential service under the RLTO, but rarely dangerous overnight. |
| Slow leak under the sink | Is it contained? It's fine in a bucket. Not fine if it's dripping into the unit below. |
| Only toilet clogged | Real hardship if it's the only toilet. Routine if there's a second bathroom. |
| Fridge stopped working | Food loss. Is that an emergency or a morning fix? |
| Power out in one unit | Could be a tripped breaker (tenant can fix it), a building problem, or a ComEd outage (not ours to fix). |
| Locked out | Safety at 2am vs. building policy (often "call a locksmith at your own cost"). |
| Window won't lock / broken front door | Security issue, not plumbing or heat. |
| AC out in a heat wave | Unclear legal status in Chicago (see assumptions). |

### Not maintenance at all: redirect
Noise complaints, neighbor disputes, rent questions, leasing questions → tell the
caller who handles it and log it for Dana.

---

## 6. What we've learned so far (draft findings for the write-up)

1. **Spotting obvious emergencies isn't the hard part.** Anyone can recognize "my
   kitchen is flooding." The hard part is the **gray zone**, and **tenants who
   exaggerate** because they've learned that saying "emergency" gets someone out
   tonight.
2. **Some emergencies aren't maintenance's to handle first.** For gas, fire, and
   carbon monoxide, the agent's most important sentence is a safety instruction, not
   a question.
3. **One broken boiler means 20 calls.** Maple Court has one boiler. When it fails,
   every unit calls. The agent should page the tech **once** and tell the other
   callers "we know, someone's on it." Otherwise it creates the same burnout it was
   meant to fix.
4. **The call is a legal record.** RLTO deadlines start at notice. What the tenant
   reported, when, and what we told them matters to Dana's liability.
5. **The rule belongs to the client.** The agent shouldn't decide what counts as an
   emergency. It should apply Dana's written policy consistently and record why it
   made each decision. If her policy changes, a setting changes, not the agent.

---

## 7. Assumptions list (what we couldn't verify)

| # | Assumption | Why it matters | How I'd check it on day 1 with a real client |
|---|---|---|---|
| A1 | A phone call to an AI agent counts as notice to the landlord under the RLTO | Affects whether the call log or a written confirmation is the legal record | Ask the client's lawyer; check what their lease says about how maintenance should be reported |
| A2 | Most after-hours calls aren't emergencies (vendor claims 90%) | Determines how much tech sleep we save | Pull 3 months of answering-service logs and label them |
| A3 | Tenants exaggerate urgency to get faster service | Determines how skeptical the agent should be | Compare "urgent" calls against what the tech actually found |
| A4 | The on-call tech can be reached by text at night | Paging only works if they see it | Ask the techs; test it; decide what happens if no reply in 10 min (call? backup person?) |
| A5 | Chicago doesn't require landlords to provide AC | Decides whether "AC out" is ever an emergency | Check the current municipal code; Chicago has discussed cooling rules |
| A6 | Tenants know where their water shutoff valve is, or the building has one per unit | Decides whether the agent can help stop a flood before the tech arrives | Building walkthrough with the techs |
| A7 | Lockouts are the tenant's responsibility | Policy varies by building | Check the lease and ask Dana |

---

## 8. What I'd ask Dana in a real discovery meeting

1. Walk me through the last three times the on-call tech got woken up. Were they real emergencies?
2. What's the worst after-hours incident you've had? What would have prevented it?
3. Is there a backup if the on-call tech doesn't answer?
4. What should the agent **never** say? (Example: promising someone will arrive by a specific time.)
5. Do you want tenants to get a text confirmation after they call?
6. If 15 people call about the boiler, who do you want to hear about it, and how many times?
7. Who changes the rules when something goes wrong, and how fast do they need to?

---

## Sources

- Chicago Bar Association, [Walking through Chicago's Heat Ordinance](https://cbaatthebar.chicagobar.org/2026/09/08/heat-season-is-upon-us-walking-through-chicagos-heat-ordinance/) (Sept 2026)
- Domu, [Landlord's Guide to the Chicago Heat Ordinance](https://www.domu.com/landlord-resources/chicago-heat-ordinance)
- Lawyers' Committee for Better Housing, [Lack of Essential Services (PDF)](https://www.lcbh.org/sites/default/files/resources/crrg-ch6-essential-services-English.pdf)
- Rentervention, [Essential Services under the Chicago RLTO](https://help.rentervention.com/article/96-chicago-rlto-essential-services)
- Metropolitan Tenants Organization, [Heat & Other Essential Services FAQ](https://www.tenants-rights.org/heat-other-essential-services-faq/)
- Digital Media Law Project, [Illinois Recording Law](https://www.dmlp.org/legal-guide/illinois-recording-law)
- Peoples Gas, [If You Smell Gas](https://www.peoplesgasdelivery.com/safety/emergency)
- Map Communications, [Property Management Answering Service](https://www.mapcommunications.com/industries/property-management/)
- Property Meld, [How to handle after-hours maintenance without a call center](https://propertymeld.com/how-to-handle-after-hours-maintenance-without-call-center/)
- Property Meld, [MAX On-Call: Redefining Maintenance Triage](https://propertymeld.com/blog/max-on-call-redefining-maintenance-triage/) (vendor marketing)
- Leasing Temps, [Maintenance On-Call and turnover](https://www.leasingtemps.com/maintenance-on-call-how-you-can-streamline-after-hours-services-and-reduce-turnover)
- Buildium, [Open API developer docs](https://developer.buildium.com/)
