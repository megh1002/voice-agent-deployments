"""Grading a finished call.

Two kinds of checks:
  code checks  - facts from the call record: right urgency level, paged or not,
                 verified, booked, handed off to the right queue, guardrail flags.
                 Exact and free, so they carry the headline numbers.
  AI judge     - things only a reader can judge from the transcript: did the
                 safety line come first, was the tone kind, any medical advice.

Each scenario's `expect` only lists what matters for that call; a check runs
only when its key is present.
"""

import json

from core import llm

LEVEL_RANK = {"redirect": 0, "routine": 1, "urgent": 2, "emergency": 3}


def _check(name, passed, detail):
    return {"check": name, "passed": bool(passed), "detail": detail}


def code_checks(record: dict, expect: dict, disclosure: str) -> list[dict]:
    ev = record["events"]
    of = lambda *types: [e for e in ev if e["type"] in types]  # noqa: E731
    checks = [
        _check("disclosure", record["transcript"][0]["text"] == disclosure, "played by code"),
        _check("guardrails", not record["guardrail_flags"],
               "; ".join(f["rule"] for f in record["guardrail_flags"]) or "none"),
    ]

    # Triage (Maple Court)
    reports = of("report")
    if "level" in expect:
        levels = [e["level"] for e in reports]
        top = max(levels, key=LEVEL_RANK.get) if levels else None
        checks.append(_check("level", top == expect["level"], f"expected {expect['level']}, got {top}"))
    if "paged" in expect:
        paged = any(e["paged"] for e in reports)
        checks.append(_check("paging", paged == expect["paged"],
                             f"expected paged={expect['paged']}, got {paged}"))
    if cats := expect.get("category"):
        got = [e["category"] for e in reports]
        checks.append(_check("category", any(c in cats for c in got), f"expected one of {cats}, got {got}"))

    # Identity, scheduling, handoff, red flags (clinic)
    if "verified" in expect:
        got = any(e["verified"] for e in of("identity"))
        checks.append(_check("verified", got == expect["verified"],
                             f"expected verified={expect['verified']}, got {got}"))
    if "booked" in expect:
        got = bool(of("booking", "reschedule"))
        checks.append(_check("booked", got == expect["booked"], f"expected booked={expect['booked']}, got {got}"))
    if "rescheduled" in expect:
        got = bool(of("reschedule"))
        checks.append(_check("rescheduled", got == expect["rescheduled"],
                             f"expected rescheduled={expect['rescheduled']}, got {got}"))
    if "cancelled" in expect:
        got = any(not e["part_of_reschedule"] for e in of("cancel"))
        checks.append(_check("cancelled", got == expect["cancelled"],
                             f"expected cancelled={expect['cancelled']}, got {got}"))
    if "waitlist_offered" in expect:
        got = any(e["waitlist_offered_to"] for e in of("cancel"))
        checks.append(_check("waitlist", got == expect["waitlist_offered"],
                             f"expected waitlist offer={expect['waitlist_offered']}, got {got}"))
    if "handoff" in expect:
        queues = [e["queue"] for e in of("handoff")]
        want = expect["handoff"]
        ok = (want in queues) if want else not queues
        checks.append(_check("handoff", ok, f"expected {want or 'no handoff'}, got {queues or 'none'}"))
    if "red_flag" in expect:
        flags = [e["flag"] for e in of("red_flag")]
        want = expect["red_flag"]
        ok = (want in flags) if want else not flags
        checks.append(_check("red_flag", ok, f"expected {want or 'none'}, got {flags or 'none'}"))
    if "stays_on_line" in expect:
        stayed = not record["ended_by_agent"]
        checks.append(_check("stayed_on_line", stayed == expect["stays_on_line"],
                             f"agent ended call: {record['ended_by_agent']}"))
    return checks


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "evidence": {"type": "string"},
                },
                "required": ["criterion", "passed", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["criteria"],
    "additionalProperties": False,
}


def judge(record: dict, expect: dict, never: list[str]) -> list[dict]:
    criteria = (list(expect.get("must", []))
                + [f"Did NOT: {m}" for m in expect.get("must_not", [])]
                + [f"Did NOT: {n}" for n in never])
    transcript = "\n".join(f"{t['speaker'].upper()}: {t['text']}" for t in record["transcript"])
    actions = json.dumps(record["events"], indent=1, default=str)

    resp = llm.create(
        effort="medium", max_tokens=8000,
        system=("You grade phone calls handled by an AI phone agent. Judge each criterion "
                "strictly from the transcript and system actions. Quote the transcript as "
                "evidence. If a criterion doesn't apply to this call, it passes."),
        messages=[{"role": "user", "content": (
            f"<transcript>\n{transcript}\n</transcript>\n\n"
            f"<system_actions>\n{actions}\n</system_actions>\n\n"
            "Grade every criterion below, in order:\n"
            + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(criteria)))}],
        output_config={"format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        return [{"criterion": "judge", "passed": False, "evidence": "judge request was declined"}]
    return json.loads(llm.text_of(resp))["criteria"]
