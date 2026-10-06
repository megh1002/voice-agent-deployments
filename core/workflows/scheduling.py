"""Scheduling: find, book, move, and cancel appointments for a verified patient.

Every tool here refuses to run until the identity workflow has verified the
caller, and acts only on that patient's own appointments. When a cancellation
frees a slot, code offers it to the first matching person on the waitlist.

Adapter methods needed: find_free_slots, book, appointments_for, cancel,
waitlist_for.
"""

import re
from datetime import date, datetime, time, timedelta

from pydantic import BaseModel

from .base import Workflow, tool

BOOKING_CLAIM = re.compile(
    r"\b(you'?re (all )?(booked|scheduled|set for)|i'?ve (booked|scheduled|moved|cancell?ed)|"
    r"(is|has been) (booked|scheduled|moved|cancell?ed))\b", re.I)


class VisitType(BaseModel):
    id: str
    description: str


class SchedulingRules(BaseModel):
    visit_types: list[VisitType]
    search_days: int = 14
    max_options: int = 3
    waitlist_backfill: bool = True


def say_when(dt: datetime) -> str:
    return dt.strftime("%A %B %-d at %-I:%M %p")


class Scheduling(Workflow):
    name = "scheduling"

    def __init__(self, playbook):
        super().__init__(playbook)
        self.rules = SchedulingRules.model_validate(playbook.section("scheduling"))

    def prompt(self):
        types = "\n".join(f"- {v.id}: {v.description}" for v in self.rules.visit_types)
        return f"""## Appointments
Only after verify_identity succeeds. Find out what kind of visit and when suits
them, then use find_open_slots. Offer at most {self.rules.max_options} options and read them
naturally. Confirm the choice before booking. To move an appointment use
reschedule_appointment (it books the new time before releasing the old one).
Before cancelling, confirm which appointment. Booking a visit the patient asks
for is fine; deciding whether they need to be seen is not your call. If they're
unsure, offer a nurse callback.

Visit types:
{types}"""

    def tools(self):
        return [
            tool("find_open_slots", "Search open appointment times.",
                 {"visit_type": {"type": "string", "enum": [v.id for v in self.rules.visit_types]},
                  "earliest_date": {"type": "string", "description": "YYYY-MM-DD, or empty for today"},
                  "latest_date": {"type": "string", "description": "YYYY-MM-DD, or empty for no limit"},
                  "time_of_day": {"type": "string", "enum": ["any", "morning", "afternoon"]},
                  "clinician": {"type": "string", "description": "Clinician's name, or empty for anyone"}}),
            tool("book_slot", "Book one of the options from find_open_slots for the verified patient.",
                 {"option_id": {"type": "string"},
                  "reason": {"type": "string", "description": "Short reason for the visit, in the patient's words"}}),
            tool("list_appointments", "List the verified patient's upcoming appointments."),
            tool("cancel_appointment", "Cancel one of the verified patient's appointments.",
                 {"appointment_id": {"type": "string"}}),
            tool("reschedule_appointment",
                 "Move an appointment: books the new option first, then cancels the old one.",
                 {"appointment_id": {"type": "string"}, "new_option_id": {"type": "string"}}),
        ]

    def handle(self, call, name, args):
        if name not in {t["name"] for t in self.tools()}:
            return None
        patient = call.state.get("patient")
        if patient is None:
            return {"error": "Caller is not verified. Use verify_identity first."}
        if name == "find_open_slots":
            return self._find(call, args)
        if name == "book_slot":
            return self._book(call, patient, args["option_id"], args["reason"])
        if name == "list_appointments":
            appts = call.adapter.appointments_for(patient.id, call.now)
            return {"appointments": [{"appointment_id": a.id, "when": say_when(a.start),
                                      "with": a.clinician, "visit_type": a.visit_type} for a in appts]}
        if name == "cancel_appointment":
            appt = self._owned(call, patient, args["appointment_id"])
            if appt is None:
                return {"error": "No such appointment for this patient."}
            self._cancel(call, patient, appt)
            return {"cancelled": True, "was": say_when(appt.start)}
        if name == "reschedule_appointment":
            appt = self._owned(call, patient, args["appointment_id"])
            if appt is None:
                return {"error": "No such appointment for this patient."}
            booked = self._book(call, patient, args["new_option_id"], "rescheduled", event="reschedule")
            if not booked.get("booked"):
                return booked
            self._cancel(call, patient, appt, as_part_of_reschedule=True)
            return {**booked, "rescheduled_from": say_when(appt.start)}

    def _find(self, call, args):
        today = call.now.date()
        start = date.fromisoformat(args["earliest_date"]) if args["earliest_date"] else today
        end = (date.fromisoformat(args["latest_date"]) if args["latest_date"]
               else today + timedelta(days=self.rules.search_days))
        lo = max(datetime.combine(start, time(0), call.now.tzinfo), call.now)
        hi = datetime.combine(end + timedelta(days=1), time(0), call.now.tzinfo)
        slots = call.adapter.find_free_slots(args["visit_type"], lo, hi)
        if args["time_of_day"] == "morning":
            slots = [s for s in slots if s.start.hour < 12]
        elif args["time_of_day"] == "afternoon":
            slots = [s for s in slots if s.start.hour >= 12]
        if args["clinician"]:
            wanted = args["clinician"].lower().replace("dr.", "").replace("doctor", "").strip()
            slots = [s for s in slots if wanted in s.clinician.lower()]
        slots = slots[:self.rules.max_options]
        call.state.setdefault("offered", {}).update({s.id: s for s in slots})
        return {"options": [{"option_id": s.id, "when": say_when(s.start), "with": s.clinician}
                            for s in slots]}

    def _book(self, call, patient, option_id, reason, event="booking"):
        slot = call.state.get("offered", {}).get(option_id)
        if slot is None:
            return {"booked": False, "error": "Unknown option. Search again with find_open_slots."}
        appt_id = call.adapter.book(slot.id, patient.id, slot.visit_type, reason)
        if appt_id is None:
            return {"booked": False, "error": "That time was just taken. Search again."}
        call.event(type=event, appointment_id=appt_id, patient_id=patient.id,
                   visit_type=slot.visit_type, clinician=slot.clinician, start=slot.start.isoformat())
        if self.pb.confirmation_sms:
            call.notifier.send_sms(patient.phone, (
                f"{self.pb.customer}: you're booked with {slot.clinician} on {say_when(slot.start)}. "
                f"To change it, call {self.pb.office_phone}."))
        return {"booked": True, "when": say_when(slot.start), "with": slot.clinician}

    def _owned(self, call, patient, appointment_id):
        return next((a for a in call.adapter.appointments_for(patient.id, call.now)
                     if a.id == appointment_id), None)

    def _cancel(self, call, patient, appt, as_part_of_reschedule=False):
        call.adapter.cancel(appt.id)
        offered_to = None
        # Backfill: offer the freed slot to the first matching person on the waitlist.
        if self.rules.waitlist_backfill:
            for person in call.adapter.waitlist_for(appt.visit_type):
                if person.id != patient.id:
                    call.notifier.send_sms(person.phone, (
                        f"{self.pb.customer}: an earlier {appt.visit_type.replace('_', ' ')} opened up "
                        f"with {appt.clinician} on {say_when(appt.start)}. Call {self.pb.office_phone} "
                        "to take it."))
                    offered_to = person.name
                    break
        call.event(type="cancel", appointment_id=appt.id, patient_id=patient.id,
                   part_of_reschedule=as_part_of_reschedule, waitlist_offered_to=offered_to)

    def check_reply(self, reply, call):
        done = call.events("booking", "reschedule", "cancel")
        if BOOKING_CLAIM.search(reply) and not done:
            return [{"rule": "claimed_booking_without_booking", "text": reply}]
        return []
