"""Checks run on every agent reply, against what actually happened on the call.

The prompt tells the model not to do these things; code catches it when it does
anyway. Checks shared by every customer live here; each workflow adds its own
(e.g. triage: "claimed a page that never happened"). A hit is flagged in the
call record and fails evals. Blocking replies before they're spoken is open (D7).
"""

import re

COST = re.compile(r"\$\s?\d|\b(costs?|charge|price)\b.{0,20}\b(about|around|roughly)\b", re.I)


def check_reply(reply: str, call) -> list[dict]:
    flags = []
    if COST.search(reply):
        flags.append({"rule": "cost_estimate", "text": reply})
    for w in call.workflows:
        flags += w.check_reply(reply, call)
    return flags
