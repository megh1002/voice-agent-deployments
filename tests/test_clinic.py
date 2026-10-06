"""Ravenswood clinic: identity, scheduling, handoffs, red flags.
These are the rules code enforces no matter what the model does.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.guardrails import check_reply
from customers.ravenswood_clinic import customer as rc

from .conftest import make_call, sent, use_tool

MON_8AM = datetime(2026, 11, 16, 8, 5, tzinfo=ZoneInfo("America/Chicago"))
MARIA = dict(full_name="Maria Gonzalez", date_of_birth="1958-03-14",
             phone_or_address="4512 N Damen Ave", caller_is="patient", caregiver_name="")


def call(outbox, phone="+17735550101"):
    return make_call(rc, phone, MON_8AM, outbox)


def test_caller_id_is_never_used_as_identity(outbox):
    c = call(outbox)  # Maria's home phone
    assert "patient" not in c.state
    assert "Maria" not in c.messages[0]["content"]
    assert "error" in use_tool(c, "list_appointments")


def test_verification_needs_name_dob_and_a_third_identifier(outbox):
    c = call(outbox)
    assert not use_tool(c, "verify_identity", **{**MARIA, "phone_or_address": "999 Fake St"})["verified"]
    r = use_tool(c, "verify_identity", **MARIA)
    assert r == {"verified": True, "patient_first_name": "Maria"}  # first name only


def test_phone_number_works_as_third_identifier(outbox):
    c = call(outbox)
    assert use_tool(c, "verify_identity", **{**MARIA, "phone_or_address": "(773) 555-0101"})["verified"]


def test_locked_after_two_failures(outbox):
    c = call(outbox)
    bad = {**MARIA, "date_of_birth": "1958-03-15"}
    use_tool(c, "verify_identity", **bad)
    use_tool(c, "verify_identity", **bad)
    assert use_tool(c, "verify_identity", **MARIA)["locked"]  # even correct details now


def test_same_name_different_person_sees_only_their_own(outbox):
    c = call(outbox, "+17735550108")
    use_tool(c, "verify_identity", full_name="Maria Gonzalez", date_of_birth="1990-06-30",
             phone_or_address="773-555-0108", caller_is="patient", caregiver_name="")
    assert use_tool(c, "list_appointments")["appointments"] == []


def test_caregiver_must_be_on_file(outbox):
    ethan = dict(full_name="Ethan Park", date_of_birth="2019-05-02",
                 phone_or_address="2240 W Leland Ave", caller_is="caregiver")
    assert use_tool(call(outbox), "verify_identity", **ethan, caregiver_name="Grace Park")["verified"]
    assert not use_tool(call(outbox), "verify_identity", **ethan, caregiver_name="Sun Park")["verified"]


def test_book_and_confirmation_text(outbox):
    c = call(outbox, "+17735550102")
    use_tool(c, "verify_identity", full_name="David Chen", date_of_birth="1985-07-22",
             phone_or_address="1830 W Montrose Ave", caller_is="patient", caregiver_name="")
    opts = use_tool(c, "find_open_slots", visit_type="same_day_sick", earliest_date="",
                    latest_date="2026-11-16", time_of_day="any", clinician="")["options"]
    assert opts and len(opts) <= 3 and "Monday November 16" in opts[0]["when"]
    r = use_tool(c, "book_slot", option_id=opts[0]["option_id"], reason="sore throat")
    assert r["booked"]
    assert "you're booked" in sent(outbox)[-1]["body"]
    # The same slot can't be booked twice.
    assert not use_tool(c, "book_slot", option_id=opts[0]["option_id"], reason="again")["booked"]


def test_cannot_book_an_option_that_was_never_offered(outbox):
    c = call(outbox)
    use_tool(c, "verify_identity", **MARIA)
    assert not use_tool(c, "book_slot", option_id="sl-morales-11161000", reason="x")["booked"]


def test_cancel_offers_slot_to_waitlist(outbox):
    c = call(outbox)
    use_tool(c, "verify_identity", **MARIA)
    appt = use_tool(c, "list_appointments")["appointments"][0]
    assert "Thursday November 19 at 10:00 AM" == appt["when"]
    assert use_tool(c, "cancel_appointment", appointment_id=appt["appointment_id"])["cancelled"]
    assert c.events("cancel")[0]["waitlist_offered_to"] == "Samuel Okoro"
    assert "opened up" in sent(outbox)[-1]["body"]


def test_cannot_cancel_someone_elses_appointment(outbox):
    c = call(outbox, "+17735550102")
    use_tool(c, "verify_identity", full_name="David Chen", date_of_birth="1985-07-22",
             phone_or_address="1830 W Montrose Ave", caller_is="patient", caregiver_name="")
    assert "error" in use_tool(c, "cancel_appointment", appointment_id="ap-5001")  # Maria's


def test_reschedule_books_new_before_releasing_old(outbox):
    c = call(outbox, "+17735550104")
    use_tool(c, "verify_identity", full_name="Robert Johnson", date_of_birth="1949-11-30",
             phone_or_address="773-555-0104", caller_is="patient", caregiver_name="")
    old = use_tool(c, "list_appointments")["appointments"][0]
    new = use_tool(c, "find_open_slots", visit_type="annual_physical", earliest_date="2026-11-30",
                   latest_date="", time_of_day="afternoon", clinician="")["options"][0]
    r = use_tool(c, "reschedule_appointment", appointment_id=old["appointment_id"],
                 new_option_id=new["option_id"])
    assert r["booked"] and r["rescheduled_from"] == old["when"]
    types = [e["type"] for e in c.record["events"]]
    assert types.index("reschedule") < types.index("cancel")
    assert [a["when"] for a in use_tool(c, "list_appointments")["appointments"]] == [new["when"]]


def test_handoff_records_verification_status(outbox):
    c = call(outbox, "+17735550113")
    r = use_tool(c, "create_handoff", queue="front_desk", request="New patient",
                 details="Moved nearby, Blue Cross", callback_number="773-555-0113", best_time="any time")
    assert "front desk" in r["tell_caller"]
    assert c.events("handoff")[0]["verified"] is False
    task = rc.staff_view(c.adapter)["Staff queues"][0]
    assert task["Queue"] == "front_desk" and "NOT VERIFIED" in task["Details"]


def test_suicidal_caller_cannot_be_hung_up_on(outbox):
    c = call(outbox, "+17735550105")
    r = use_tool(c, "report_red_flag", flag="suicidal_thoughts", what_caller_said="thinking of ending it")
    assert "Stay on the line" in r["next"]
    assert use_tool(c, "end_call")["ok"] is False and not c.ended
    assert "ON THE LINE" in sent(outbox)[-1]["body"]


def test_emergency_symptoms_alert_staff_and_allow_hang_up(outbox):
    c = call(outbox, "+17735550104")
    use_tool(c, "report_red_flag", flag="emergency_symptoms", what_caller_said="chest tight")
    assert c.events("red_flag")[0]["staff_alerted"]
    assert use_tool(c, "end_call")["ok"] and c.ended


def test_booking_claim_guardrail(outbox):
    c = call(outbox)
    assert check_reply("Great, you're all booked for Thursday.", c)[0]["rule"] == "claimed_booking_without_booking"


def test_identity_prompt_follows_the_playbook(outbox):
    c = call(outbox)
    ident = next(w for w in c.workflows if w.name == "identity")
    assert "phone number on file. If they don't know it" in c.system
    assert "D-A-M-E-N" in c.system
    ident.rules.read_back = False
    assert "D-A-M-E-N" not in ident.prompt()


def test_misheard_address_fails_until_corrected(outbox):
    c = call(outbox)
    misheard = {**MARIA, "phone_or_address": "4512 N Tamen Ave"}
    assert not use_tool(c, "verify_identity", **misheard)["verified"]   # why read-back matters
    assert use_tool(c, "verify_identity", **MARIA)["verified"]           # corrected, second attempt


def test_address_needs_the_actual_street_name(outbox):
    for wrong in ("4512 Anything Ave", "4512 N Ave", "4512", "9999 N Damen Ave"):
        assert not use_tool(call(outbox), "verify_identity", **{**MARIA, "phone_or_address": wrong})["verified"], wrong
    for right in ("4512 north damen avenue", "4512 Damen", "4512 N. Damen Ave."):
        assert use_tool(call(outbox), "verify_identity", **{**MARIA, "phone_or_address": right})["verified"], right
