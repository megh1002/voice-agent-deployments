"""Identity: verify who's calling before anything private is discussed.

The model collects what the caller says (name, date of birth, one more
identifier). Code checks it against the record. On a match, code stores the
patient in the call's state; the model only learns the first name. Other
workflows read the verified patient from state, so the model can never act on
a record it wasn't verified for.

Caller ID is deliberately NOT used: families share phones.

Adapter methods needed: find_patient(full_name, birth_date) -> list[PatientRecord]
"""

import re

from pydantic import BaseModel

from .base import Workflow, tool


class IdentityRules(BaseModel):
    max_attempts: int = 2
    caregivers: str = "on_file_only"  # caregivers must be listed as authorized
    phone_first: bool = True   # digits survive speech-to-text better than street names
    read_back: bool = True     # confirm details (spelling names) before checking them


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)[-10:]


# Words that don't identify a street on their own: directions and suffixes.
NOT_STREET_NAME = {"n", "s", "e", "w", "north", "south", "east", "west", "ave", "avenue", "st",
                   "street", "rd", "road", "blvd", "boulevard", "dr", "drive", "ln", "lane",
                   "ct", "court", "pl", "place", "pkwy", "parkway", "way", "ter", "terrace"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _third_identifier_matches(said: str, p) -> bool:
    """Phone on file (all 10 digits) or street address (house number AND street name).
    Directions and suffixes like "N" or "Ave" never count as a match on their own."""
    if len(_digits(said)) >= 7:
        return _digits(said) == _digits(p.phone)
    record, heard = _words(p.address_line), _words(said)
    number, street = record[0], [w for w in record[1:] if w not in NOT_STREET_NAME]
    return number in heard and bool(street) and all(w in heard for w in street)


class Identity(Workflow):
    name = "identity"

    def __init__(self, playbook):
        super().__init__(playbook)
        self.rules = IdentityRules.model_validate(playbook.section("identity"))

    def prompt(self):
        third = ("the phone number on file. If they don't know it, ask for their street address instead"
                 if self.rules.phone_first else "either the phone number on file or their street address")
        read_back = ("""
Before calling verify_identity, read the details back and ask the caller to
confirm, spelling any street or last name letter by letter (for example: "That's
Damen, D-A-M-E-N?"). Speech recognition often mishears names, and a wrong letter
would fail a correct caller. Only read back what the caller told you.""" if self.rules.read_back else "")
        return f"""## Verifying identity
Before discussing or changing anything about a patient (appointments included),
verify identity with verify_identity: full name, date of birth, and {third}.
Ask for these naturally, a couple at a time. If someone calls for another person
(a parent for a child, an adult child for a parent), collect the patient's
details and the caller's own name.{read_back}
Never hint at whether a name or birth date matched. After {self.rules.max_attempts} failed
attempts, stop trying and offer a callback from the front desk instead.
You don't need to verify someone to give general information (hours, location)
or to follow red flag instructions."""

    def tools(self):
        return [tool(
            "verify_identity",
            "Check the caller's identity against the patient record. Required before any "
            "scheduling tool. Returns only whether it matched and the patient's first name.",
            {"full_name": {"type": "string", "description": "Patient's full name"},
             "date_of_birth": {"type": "string", "description": "Patient's date of birth, YYYY-MM-DD"},
             "phone_or_address": {"type": "string",
                                  "description": "Phone number on file or street address, as the caller said it"},
             "caller_is": {"type": "string", "enum": ["patient", "caregiver"]},
             "caregiver_name": {"type": "string",
                                "description": "Caller's own full name if caregiver, else empty"}},
        )]

    def handle(self, call, name, args):
        if name != "verify_identity":
            return None
        attempts = call.state.get("identity_attempts", 0)
        if attempts >= self.rules.max_attempts:
            return {"verified": False, "locked": True,
                    "tell_caller": "Too many attempts. Offer a callback from the front desk."}
        call.state["identity_attempts"] = attempts + 1

        matches = [p for p in call.adapter.find_patient(args["full_name"], args["date_of_birth"])
                   if _third_identifier_matches(args["phone_or_address"], p)]
        caregiver = args["caller_is"] == "caregiver"
        if matches and caregiver:
            who = args["caregiver_name"].strip().lower()
            matches = [p for p in matches if who and any(who == x.lower() for x in p.proxies)]

        ok = len(matches) == 1
        call.event(type="identity", verified=ok, attempt=attempts + 1,
                   as_caregiver=caregiver, patient_id=matches[0].id if ok else None)
        if ok:
            call.state["patient"] = matches[0]
            return {"verified": True, "patient_first_name": matches[0].name.split()[0]}
        left = self.rules.max_attempts - attempts - 1
        if caregiver and left:
            hint = "Ask them to double-check the details. If they are a caregiver not on file, the front desk can help."
        else:
            hint = "Ask them to double-check the details." if left else "Offer a front desk callback."
        return {"verified": False, "attempts_left": left, "tell_caller": hint}
