"""Identity: verify who's calling before anything private is discussed.

The model collects what the caller says (name, date of birth, one more
identifier). Code checks it against the record. On a match, code stores the
patient in the call's state; the model only learns the first name. Other
workflows read the verified patient from state, so the model can never act on
a record it wasn't verified for.

Caller ID is deliberately NOT used: families share phones.

Speech-to-text mishears names ("Gonzales" for Gonzalez, "Tamen" for Damen), and
making callers spell them is slow and still fails. So names and street names
match if they sound alike, but only when the birth date and the phone number
(or house number) match exactly. The exact identifiers carry the security (D29).

Adapter methods needed: find_patients_born_on(birth_date) -> list[PatientRecord]
"""

import re

from pydantic import BaseModel

from .base import Workflow, tool


class IdentityRules(BaseModel):
    max_attempts: int = 2
    caregivers: str = "on_file_only"  # caregivers must be listed as authorized
    phone_first: bool = True   # digits survive speech-to-text better than street names
    sounds_alike: bool = True  # names and street names may match by sound (D29)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)[-10:]


# Words that don't identify a street on their own: directions and suffixes.
NOT_STREET_NAME = {"n", "s", "e", "w", "north", "south", "east", "west", "ave", "avenue", "st",
                   "street", "rd", "road", "blvd", "boulevard", "dr", "drive", "ln", "lane",
                   "ct", "court", "pl", "place", "pkwy", "parkway", "way", "ter", "terrace"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


SOUND_GROUPS = {"bfpv": "1", "cgjkqsxz": "2", "dt": "3", "l": "4", "mn": "5", "r": "6"}
SOUND = {ch: code for letters, code in SOUND_GROUPS.items() for ch in letters}


def _sound(word: str) -> str:
    """A sounds-alike key, Soundex-style but coding the first letter too, so D/T and
    S/Z land together: Gonzalez = Gonzales, Damen = Tamen. Vowels are dropped."""
    key = ""
    for ch in word.lower():
        code = SOUND.get(ch, "")
        if code and not key.endswith(code):
            key += code
    return key


def _same_word(said: str, record: str, sounds_alike: bool) -> bool:
    if said.lower() == record.lower():
        return True
    return sounds_alike and bool(_sound(record)) and _sound(said) == _sound(record)


def _name_matches(said: str, p, sounds_alike: bool) -> bool:
    """First and last name, each exactly or (if allowed) by sound."""
    heard, record = _words(said), _words(p.name)
    if len(heard) < 2:
        return False
    return (_same_word(heard[0], record[0], sounds_alike)
            and _same_word(heard[-1], record[-1], sounds_alike))


def _third_identifier_matches(said: str, p, sounds_alike: bool = False) -> bool:
    """Phone on file (all 10 digits) or street address (house number AND street name).
    Directions and suffixes like "N" or "Ave" never count as a match on their own."""
    if len(_digits(said)) >= 7:
        return _digits(said) == _digits(p.phone)
    record, heard = _words(p.address_line), _words(said)
    number, street = record[0], [w for w in record[1:] if w not in NOT_STREET_NAME]
    return number in heard and bool(street) and all(
        any(_same_word(h, w, sounds_alike) for h in heard if h not in NOT_STREET_NAME) for w in street)


# The agent saying details "match" before the check ran (seen on the first live call).
IDENTITY_CLAIM = re.compile(r"\b(that matches|matches (what|our)|you'?re (now )?verified|"
                            r"(i'?ve|i have) verified|identity (is )?(confirmed|verified))\b", re.I)


class Identity(Workflow):
    name = "identity"

    def __init__(self, playbook):
        super().__init__(playbook)
        self.rules = IdentityRules.model_validate(playbook.section("identity"))

    def prompt(self):
        third = ("the phone number on file. If they don't know it, ask for their street address instead"
                 if self.rules.phone_first else "either the phone number on file or their street address")
        spelling = ("""
Don't ask callers to spell names or streets, and don't read details back before
checking: the check already allows for names that sound alike. Call
verify_identity as soon as you have all three details.""" if self.rules.sounds_alike else "")
        return f"""## Verifying identity
Before discussing or changing anything about a patient (appointments included),
verify identity with verify_identity: full name, date of birth, and {third}.
Ask for these naturally, a couple at a time. If someone calls for another person
(a parent for a child, an adult child for a parent), collect the patient's
details and the caller's own name.{spelling}
If the caller pauses partway through a number, don't comment on the partial
number; just say "Mm-hm" and let them finish.
Never say the details match, or that the caller is verified, until verify_identity
says so. If it fails, don't guess which detail was wrong and never hint at whether
a name or birth date matched; ask them to repeat the details, or offer the street
address instead of the phone number. After {self.rules.max_attempts} failed
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

        loose = self.rules.sounds_alike
        born = call.adapter.find_patients_born_on(args["date_of_birth"])
        exact = [p for p in born if _name_matches(args["full_name"], p, False)
                 and _third_identifier_matches(args["phone_or_address"], p, False)]
        # Exact matches win; sounds-alike only when nothing matches exactly.
        matches = exact or [p for p in born if _name_matches(args["full_name"], p, loose)
                            and _third_identifier_matches(args["phone_or_address"], p, loose)]
        caregiver = args["caller_is"] == "caregiver"
        if matches and caregiver:
            who = args["caregiver_name"].strip().lower()
            matches = [p for p in matches if who and any(who == x.lower() for x in p.proxies)]

        ok = len(matches) == 1
        call.event(type="identity", verified=ok, attempt=attempts + 1, as_caregiver=caregiver,
                   patient_id=matches[0].id if ok else None,
                   matched_by=("exact" if exact else "sounds_alike") if ok else None)
        if ok:
            call.state["patient"] = matches[0]
            return {"verified": True, "patient_first_name": matches[0].name.split()[0]}
        left = self.rules.max_attempts - attempts - 1
        if caregiver and left:
            hint = "Ask them to double-check the details. If they are a caregiver not on file, the front desk can help."
        else:
            hint = "Ask them to double-check the details." if left else "Offer a front desk callback."
        return {"verified": False, "attempts_left": left, "tell_caller": hint}

    def check_reply(self, reply, call):
        if IDENTITY_CLAIM.search(reply) and "patient" not in call.state:
            return [{"rule": "claimed_verified_without_check", "text": reply}]
        return []
