# Findings

What we learned from eval runs and test calls: what broke, why, and what we
changed. These become the case study and the interview stories.

---

## F1. A badly worded eval criterion can fail a correct agent (2026-10-06)

- **Scenario:** `chest_pain_wants_appointment`. The caller asks for an
  appointment and mentions chest tightness only after identity questions.
- **What the agent did:** started verifying normally. The moment symptoms were
  mentioned, it said "This needs emergency care. Please hang up and call 911
  right now," with no follow-up questions, alerted staff, and ended the call.
  Correct.
- **What was wrong:** my criterion said "call 911 *before asking for any
  identifying details*," which is impossible when symptoms come up later. The
  AI judge read it sensibly and passed it; a stricter judge would have failed a
  correct agent.
- **Change:** reworded to "as soon as the symptoms are mentioned … with no
  further questions."
- **Lesson:** evals need reviewing too. Criteria should describe the behavior
  that matters (the trigger and the response), not assume when the caller says it.
- **Cost:** $0.07 for the call (9 API requests).

## F2. Speech-to-text mishears names, and that breaks identity checks (2026-10-06)

- **What happened:** in Meghna's first voice call, "4512 N Damen Ave" was
  transcribed as "Tamen Avenue". The address is the third identifier for HIPAA
  verification, so a correct caller would fail verification.
- **Why it matters:** street names, surnames, and medication names are exactly
  the words speech recognition gets wrong most, especially with accents, and
  they're the words identity checks and refills depend on. A text-only eval
  never catches this.
- **Decision (D23):** ask for the phone number first, and read details back
  (spelling names) before checking. Close matches are NOT accepted. Better
  speech-to-text is noted for the voice-platform phase. New eval scenario:
  `misheard_street_name`.
- **Options considered:**
  - Prefer the phone number as the third identifier: digits transcribe more reliably than names.
  - Read back and confirm: "Did you say Damen, D-A-M-E-N?"
  - Use a speech-to-text service that accepts a list of expected words
    (street names, clinicians, medications) to bias recognition.
  - Tolerant matching in code (Tamen ≈ Damen). Easiest, but it loosens a
    security check, which is a trade-off to decide deliberately.
  - Add accent and mishearing variants to the eval scenarios, so the text
    evals cover what voice gets wrong.

## F3. Browser text-to-speech sounds robotic (2026-10-06)

- The free built-in browser voice sounds clearly artificial. For a phone line,
  voice quality is part of whether callers trust the agent and stay on.
- **Options:** pick the best built-in voice on the machine (a small win), or
  move to the real voice layer (Vapi or Retell, decision D2), which uses natural
  voices and phone-grade speech recognition.

## F4. Web app: switching tabs drops the live call (2026-10-06)

- Leaving "Try a call" for "Staff view" lost the call in progress, and the
  "Behind the scenes" panel was hard to see during the call.
- **Fixed (2026-10-06):** the call now survives tab switches and page reloads.
  A side panel next to the call switches between "Behind the scenes" and a live
  "Staff view", stays on screen while you talk, and refreshes after every turn.
  Also added a voice picker that ranks the most natural voices first (F3).

## F5. The address check was too loose: "Ave" alone counted as a match (2026-10-07)

- **Found by:** a unit test written for F2. It expected "4512 N Tamen Ave" to
  fail verification, and it passed instead.
- **Cause:** the check needed the house number plus *any* word from the street,
  and "Ave" is a word from the street. "4512 Anything Ave" would have unlocked
  Maria Gonzalez's record. A privacy hole in the HIPAA identity step.
- **Fix:** the house number and every real street-name word must match;
  directions and suffixes (N, Ave, St, ...) never count on their own. Tests now
  cover wrong streets, wrong numbers, and spoken variants ("north damen avenue").
- **Lesson:** a loose matcher that looks fine in a demo is exactly where privacy
  bugs hide. Tests for the "should fail" cases matter as much as the happy path.
