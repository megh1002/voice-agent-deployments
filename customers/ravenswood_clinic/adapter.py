"""Ravenswood's integration: their EHR (FHIR) + the front desk's waitlist sheet.

Talks to the EHR over HTTP only, using FHIR search and resources. If the real
EHR books through its own non-FHIR API (common, see discovery.md §6), only
book() and cancel() change.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from core.adapter import AppointmentInfo, PatientRecord, SlotInfo

WAITLIST_CSV = Path(__file__).parent / "waitlist.csv"
CHI = ZoneInfo("America/Chicago")


@dataclass
class WaitlistEntry:
    id: str
    name: str
    phone: str


def _ref_id(ref: str) -> str:
    return ref.split("/", 1)[1]


class RavenswoodAdapter:
    def __init__(self, http: httpx.Client, waitlist_csv: Path = WAITLIST_CSV):
        self.http = http
        self.waitlist_csv = waitlist_csv
        self._clinicians: dict[str, str] | None = None

    def _search(self, resource: str, **params) -> list[dict]:
        r = self.http.get(f"/fhir/{resource}", params=params)
        r.raise_for_status()
        return [e["resource"] for e in r.json().get("entry", [])]

    def _clinician_names(self) -> dict[str, str]:
        if self._clinicians is None:
            self._clinicians = {p["id"]: p["name"][0]["text"] for p in self._search("Practitioner")}
        return self._clinicians

    def _local(self, iso: str) -> datetime:
        return datetime.fromisoformat(iso).replace(tzinfo=CHI)

    # ---- identity ---------------------------------------------------------------

    def find_patient(self, full_name: str, birth_date: str) -> list[PatientRecord]:
        parts = full_name.strip().split()
        if len(parts) < 2:
            return []
        out = []
        for p in self._search("Patient", given=parts[0], family=parts[-1], birthdate=birth_date):
            proxies = [f"{r['name'][0]['given'][0]} {r['name'][0]['family']}"
                       for r in self._search("RelatedPerson", patient=f"Patient/{p['id']}")]
            n = p["name"][0]
            out.append(PatientRecord(
                id=p["id"], name=f"{n['given'][0]} {n['family']}", birth_date=p["birthDate"],
                phone=p["telecom"][0]["value"], address_line=p["address"][0]["line"][0],
                proxies=proxies))
        return out

    # ---- scheduling ---------------------------------------------------------------

    def find_free_slots(self, visit_type: str, lo: datetime, hi: datetime) -> list[SlotInfo]:
        fmt = "%Y-%m-%dT%H:%M:%S"
        slots = self._search("Slot", status="free", **{"service-type": visit_type},
                             start=[f"ge{lo.astimezone(CHI):{fmt}}", f"lt{hi.astimezone(CHI):{fmt}}"])
        names = self._clinician_names()
        return [SlotInfo(id=s["id"], start=self._local(s["start"]),
                         clinician=names[_ref_id(s["schedule"]["reference"])],
                         visit_type=s["serviceType"][0]["text"]) for s in slots]

    def book(self, slot_id: str, patient_id: str, visit_type: str, reason: str) -> str | None:
        r = self.http.post("/fhir/Appointment", json={
            "resourceType": "Appointment", "status": "booked",
            "serviceType": [{"text": visit_type}], "description": reason,
            "slot": [{"reference": f"Slot/{slot_id}"}],
            "participant": [{"actor": {"reference": f"Patient/{patient_id}"}}],
        })
        if r.status_code == 409:
            return None
        r.raise_for_status()
        return r.json()["id"]

    def appointments_for(self, patient_id: str, now: datetime) -> list[AppointmentInfo]:
        names = self._clinician_names()
        out = []
        for a in self._search("Appointment", patient=f"Patient/{patient_id}", status="booked"):
            start = self._local(a["start"])
            if start < now:
                continue
            pr = next(_ref_id(p["actor"]["reference"]) for p in a["participant"]
                      if p["actor"]["reference"].startswith("Practitioner/"))
            out.append(AppointmentInfo(id=a["id"], start=start, clinician=names[pr],
                                       visit_type=a["serviceType"][0]["text"],
                                       slot_id=_ref_id(a["slot"][0]["reference"])))
        return out

    def cancel(self, appointment_id: str) -> None:
        r = self.http.get(f"/fhir/Appointment/{appointment_id}")
        r.raise_for_status()
        appt = {**r.json(), "status": "cancelled"}
        self.http.put(f"/fhir/Appointment/{appointment_id}", json=appt).raise_for_status()

    def waitlist_for(self, visit_type: str) -> list[WaitlistEntry]:
        with self.waitlist_csv.open() as f:
            return [WaitlistEntry(row["patient_id"], row["name"], row["phone"])
                    for row in csv.DictReader(f) if row["visit_type"] == visit_type]

    # ---- handoffs ---------------------------------------------------------------

    def create_task(self, queue: str, description: str, priority: str,
                    patient_id: str | None) -> str:
        task = {"resourceType": "Task", "intent": "order", "priority": priority,
                "code": {"text": queue}, "description": description}
        if patient_id:
            task["for"] = {"reference": f"Patient/{patient_id}"}
        r = self.http.post("/fhir/Task", json=task)
        r.raise_for_status()
        return r.json()["id"]
