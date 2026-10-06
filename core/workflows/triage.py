"""Triage: understand a problem, decide how urgent it is, act on it.

Used by Maple Court (after-hours maintenance). The model picks a category from
the playbook; code decides the level, pages on-call or creates a ticket, avoids
duplicate pages for building-wide problems, and texts the caller a confirmation.

Adapter methods needed: find_caller, unit_exists, create_ticket,
open_emergency_since, on_call.
"""

import re
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from core.adapter import Caller
from .base import Workflow, tool

Level = Literal["emergency", "urgent", "routine", "redirect"]
Action = Literal["page_oncall", "ticket_high", "ticket_normal", "note_for_manager"]
PRIORITY = {"page_oncall": "High", "ticket_high": "High",
            "ticket_normal": "Normal", "note_for_manager": "Low"}
DUPLICATE_WINDOW = timedelta(hours=12)


class LevelRule(BaseModel):
    action: Action
    tell_caller: str


class Category(BaseModel):
    id: str
    description: str
    level: Level
    safety_first: str | None = None
    guidance: str | None = None
    seasonal: Literal["heating"] | None = None
    building_wide: bool = False


class Season(BaseModel):
    start: str  # "MM-DD"
    end: str

    def contains(self, when: datetime) -> bool:
        md = when.strftime("%m-%d")
        if self.start <= self.end:
            return self.start <= md < self.end
        return md >= self.start or md < self.end  # wraps over New Year


class TriageRules(BaseModel):
    levels: dict[Level, LevelRule]
    categories: list[Category]
    heating_season: Season | None = None

    def category(self, category_id: str) -> Category:
        return next(c for c in self.categories if c.id == category_id)

    def resolve_level(self, category_id: str, when: datetime) -> tuple[Level, str]:
        c = self.category(category_id)
        if c.seasonal == "heating" and self.heating_season and not self.heating_season.contains(when):
            return "routine", f"{c.id} is outside heating season, so it is routine"
        return c.level, f"playbook sets {c.id} to {c.level}"


PAGE_CLAIM = re.compile(
    r"\b(paged|been notified|on (his|her|their|the) way|someone (is|will be) coming|"
    r"technician (is|will be) (coming|heading|there))\b", re.I)
TIME_PROMISE = re.compile(
    r"\b(within|in (the next)?)\s+(\d+|a few|an?|one|two|three|fifteen|thirty|twenty)\s+"
    r"(minutes?|hours?)\b|\bby \d{1,2}(:\d\d)?\s*(am|pm)?\b", re.I)


class Triage(Workflow):
    name = "triage"

    def __init__(self, playbook):
        super().__init__(playbook)
        self.rules = TriageRules.model_validate(playbook.section("triage"))

    def context(self, call):
        caller = call.adapter.find_caller(call.caller_phone)
        call.state["caller"] = caller or Caller("Unknown caller", None, call.caller_phone)
        if caller:
            return f"Caller ID matches tenant {caller.name}, unit {caller.unit}."
        return "Caller ID is not on file. Ask for their name and unit."

    def prompt(self):
        cats = []
        for c in self.rules.categories:
            line = f"- {c.id}: {c.description}"
            if c.safety_first:
                line += f'\n  SAFETY FIRST - say this before anything else: "{c.safety_first}"'
            if c.guidance:
                line += f'\n  Helpful guidance you can give: "{c.guidance}"'
            cats.append(line)
        return f"""## Maintenance problems
1. If the caller describes anything dangerous, give the SAFETY FIRST line for that
   category immediately, before any questions. For gas, don't keep them on the
   phone: report it right away with whatever you know and let them go.
2. Ask at most two or three short questions, only what you need to pick the right
   category (for example: is the water spreading or contained?).
3. Make sure you know the unit. If caller ID didn't identify them, ask for their
   name and unit, and check it with verify_unit.
4. Call report_issue with the best matching category. You don't decide how urgent
   it is; the building's playbook does.
5. Tell the caller what report_issue says to tell them, without adding promises.
   Give any helpful guidance for the category.
If the caller reports a second, separate problem, report it separately.

Categories:
{chr(10).join(cats)}"""

    def tools(self):
        return [
            tool("verify_unit", "Check that a unit number the caller gave exists in this building.",
                 {"unit": {"type": "string", "description": "Unit number, e.g. 2C"}}),
            tool("report_issue",
                 "Report the caller's problem. The playbook decides urgency and runs the right "
                 "action (page on-call or create a ticket). Returns what actually happened and "
                 "what to tell the caller. Call once per problem.",
                 {"category": {"type": "string", "enum": [c.id for c in self.rules.categories]},
                  "summary": {"type": "string",
                              "description": "One or two sentences: what's wrong, where, how bad."},
                  "unit": {"type": "string",
                           "description": "Unit number, or 'unknown' if the caller won't give one."}}),
        ]

    def handle(self, call, name, args):
        if name == "verify_unit":
            return {"exists": call.adapter.unit_exists(args["unit"])}
        if name == "report_issue":
            caller = call.state["caller"]
            unit = None if args["unit"].lower() == "unknown" else args["unit"]
            event = self.report(call, category=args["category"], summary=args["summary"],
                                unit=unit or caller.unit, caller=caller)
            return {"level": event["level"], "what_happened": event["actions"],
                    "tell_caller": event["tell_caller"]}
        return None

    def report(self, call, *, category, summary, unit, caller) -> dict:
        """The deterministic part. Also used directly by tests and eval setup."""
        now, adapter = call.now, call.adapter
        level, reason = self.rules.resolve_level(category, now)
        rule = self.rules.levels[level]
        cat = self.rules.category(category)
        where = f"unit {unit}" if unit else "unit unknown"
        ev = {"type": "report", "category": category, "level": level, "reason": reason,
              "ticket_id": None, "paged": None, "page_failed": False, "duplicate_of": None,
              "confirmation_sent": False, "actions": [], "tell_caller": ""}

        # A building-wide emergency that's already open: don't wake anyone again.
        if level == "emergency" and cat.building_wide:
            existing = adapter.open_emergency_since(category, now - DUPLICATE_WINDOW)
            if existing:
                ev["duplicate_of"] = existing
                ev["actions"].append(f"duplicate of ticket {existing}, no new page")
                ev["tell_caller"] = ("This has already been reported, and the on-call technician "
                                     "is already working on it. I've added your report too.")
                return call.event(**ev)

        ev["ticket_id"] = adapter.create_ticket(
            title=f"[{level.upper()}] {category} ({where})",
            description=f"{summary}\nReported by {caller.name} ({caller.phone}) at {now:%Y-%m-%d %H:%M}.",
            category=category, priority=PRIORITY[rule.action], unit=unit)
        ev["actions"].append(f"created ticket {ev['ticket_id']}")

        if rule.action == "page_oncall":
            body = (f"{self.pb.customer.upper()} EMERGENCY: {category}, {where}. {summary} "
                    f"Call back {caller.name} at {caller.phone}. Ticket {ev['ticket_id']}.")
            for contact in adapter.on_call(now):
                if call.notifier.send_sms(contact.phone, body):
                    ev["paged"] = contact.name
                    ev["actions"].append(f"paged {contact.name}")
                    break
            if ev["paged"] is None:
                ev["page_failed"] = True
                ev["actions"].append("page FAILED for primary and backup")
                ev["tell_caller"] = (
                    "I wasn't able to reach the on-call technician. If anyone is in danger, "
                    "call 911 now. Otherwise, please call back in ten minutes and I'll try "
                    f"again. Your report is logged as ticket {ev['ticket_id']}.")
                return call.event(**ev)

        ev["tell_caller"] = rule.tell_caller
        # Written confirmation: the RLTO clock starts at notice, so both sides
        # get a dated record of the report.
        if self.pb.confirmation_sms and caller.phone:
            ev["confirmation_sent"] = call.notifier.send_sms(caller.phone, (
                f"{self.pb.customer}: we received your maintenance report ({category}, {where}) "
                f"at {now:%-I:%M %p on %b %-d}. Ticket {ev['ticket_id']}."))
            if ev["confirmation_sent"]:
                ev["actions"].append("sent confirmation text to caller")
        return call.event(**ev)

    def check_reply(self, reply, call):
        flags = []
        paged = any(e.get("paged") or e.get("duplicate_of") for e in call.events("report"))
        if PAGE_CLAIM.search(reply) and not paged:
            flags.append({"rule": "claimed_page_without_page", "text": reply})
        if TIME_PROMISE.search(reply) and "call back in ten minutes" not in reply:
            flags.append({"rule": "promised_time", "text": reply})
        return flags
