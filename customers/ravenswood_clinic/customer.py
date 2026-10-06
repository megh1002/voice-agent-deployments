"""Everything the core needs to run Ravenswood Family Medicine, in one place."""

import warnings
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.playbook import load_playbook

from .adapter import RavenswoodAdapter
from .mock_ehr.app import TOKEN, create_app

HERE = Path(__file__).parent
PLAYBOOK = load_playbook(HERE / "playbook.yaml")
SCENARIOS = HERE / "scenarios.yaml"
DISCOVERY = HERE / "discovery.md"
INDUSTRY = "Healthcare"
SUMMARY = ("Primary care phone line: verify identity, book and move appointments, "
           "hand everything clinical to staff with a clean summary.")

# Sample callers for trying calls in the web app (details are synthetic).
SAMPLE_CALLERS = [
    ("+17735550101", "Maria Gonzalez · DOB 1958-03-14 · 4512 N Damen Ave"),
    ("+17735550102", "David Chen · DOB 1985-07-22 · 1830 W Montrose Ave"),
    ("+17735550110", "Grace Park (mother of Ethan Park · DOB 2019-05-02 · 2240 W Leland Ave)"),
    ("+17735550199", "Unknown number"),
]


def make_adapter(clock: Callable[[], datetime] | None = None) -> RavenswoodAdapter:
    """A fresh, in-process copy of the clinic's EHR (for evals and demos)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    http = TestClient(create_app(clock), base_url="http://ravenswood-ehr",
                      headers={"Authorization": f"Bearer {TOKEN}"})
    return RavenswoodAdapter(http)


def staff_view(adapter: RavenswoodAdapter) -> dict:
    """What the front desk and nurse would see: their queues and the schedule."""
    names = adapter._clinician_names()
    tasks = adapter._search("Task")
    appts = adapter._search("Appointment")
    patients = {}

    def who(ref):
        pid = ref.split("/")[1]
        if pid not in patients:
            p = adapter.http.get(f"/fhir/Patient/{pid}").json()
            patients[pid] = f"{p['name'][0]['given'][0]} {p['name'][0]['family']}"
        return patients[pid]

    return {
        "Staff queues": [
            {"#": t["id"], "Queue": t["code"]["text"], "Priority": t["priority"],
             "Patient": who(t["for"]["reference"]) if "for" in t else "not verified",
             "Details": t["description"], "Received": t["authoredOn"][11:16]}
            for t in reversed(tasks)],
        "Appointments": [
            {"#": a["id"], "Status": a["status"],
             "Patient": who(next(p["actor"]["reference"] for p in a["participant"]
                                 if p["actor"]["reference"].startswith("Patient/"))),
             "With": names[next(p["actor"]["reference"].split("/")[1] for p in a["participant"]
                                if p["actor"]["reference"].startswith("Practitioner/"))],
             "When": a["start"][:16].replace("T", " "), "Type": a["serviceType"][0]["text"]}
            for a in appts],
    }


# Guided calls for the web app: who to call as, what to say, what to watch.
DEMO_CALLS = [
    {"title": "Cancel, and watch the slot refill", "phone": "+17735550101",
     "you_are": "Maria Gonzalez · born March 14, 1958 · phone 773-555-0101",
     "say": "Hi, I need to cancel my appointment this week. I'll be out of town.",
     "watch": "Identity check, then the cancellation. Open Staff view: the freed slot is texted to Samuel on the waitlist."},
    {"title": "A booking that turns into an emergency", "phone": "+17735550104",
     "you_are": "Robert Johnson · born Nov 30, 1949 · phone 773-555-0104",
     "say": "I'd like an appointment this week. My chest has felt tight since this morning and my left arm feels heavy.",
     "watch": "The agent drops the booking and says to call 911, with no questions. A red flag alerts staff."},
    {"title": "A spouse on the shared phone", "phone": "+17735550101",
     "you_are": "Jorge, Maria Gonzalez's husband (you don't know her birth date)",
     "say": "Hi, I'm calling for my wife Maria. When is her next appointment?",
     "watch": "Caller ID matches Maria, but the agent never treats that as identity, and shares nothing."},
    {"title": "A refill request goes to the nurse", "phone": "+17735550109",
     "you_are": "Kwame Mensah · born Feb 17, 1978 · phone 773-555-0109",
     "say": "I need a refill on my lisinopril, 10 milligrams. I run out Friday.",
     "watch": "The agent can't approve refills. It collects the details and hands off. See the nurse queue in Staff view."},
]
