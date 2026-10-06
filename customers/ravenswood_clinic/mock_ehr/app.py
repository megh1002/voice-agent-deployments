"""Mock EHR scheduling API for Ravenswood Family Medicine (the client's system).

Uses FHIR R4 resource shapes and search conventions (Patient, RelatedPerson,
Practitioner, Slot, Appointment, Task, searchset Bundles). Real EHRs often
don't allow booking through FHIR (see discovery.md §6); this mock does, and
the agent only reaches it through the adapter, so swapping in a vendor's own
booking API later changes only the adapter.

Run:  .venv/bin/uvicorn customers.ravenswood_clinic.mock_ehr.app:app --port 8002
"""

import os
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query

from .seed import PRACTITIONERS, build

TOKEN = os.environ.get("EHR_TOKEN", "dev-token")
CHI = ZoneInfo("America/Chicago")


def require_token(authorization: str | None = Header(None)):
    # Real EHRs use OAuth 2.0 (SMART on FHIR). A static bearer token stands in.
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "Invalid token")


def bundle(resources: list[dict]) -> dict:
    return {"resourceType": "Bundle", "type": "searchset", "total": len(resources),
            "entry": [{"resource": r} for r in resources]}


def outcome(status: int, text: str):
    raise HTTPException(status, {"resourceType": "OperationOutcome",
                                 "issue": [{"severity": "error", "diagnostics": text}]})


def create_app(clock: Callable[[], datetime] | None = None) -> FastAPI:
    clock = clock or (lambda: datetime.now(CHI))
    patients, related, slots, appointments = build(clock().date())
    tasks: dict[str, dict] = {}
    app = FastAPI(title="Ravenswood EHR (mock, FHIR R4 shapes)",
                  dependencies=[Depends(require_token)])

    @app.get("/fhir/Patient")
    def search_patients(family: str | None = None, given: str | None = None,
                        birthdate: str | None = None):
        out = []
        for p in patients.values():
            n = p["name"][0]
            if family and n["family"].lower() != family.lower():
                continue
            if given and n["given"][0].lower() != given.lower():
                continue
            if birthdate and p["birthDate"] != birthdate:
                continue
            out.append(p)
        return bundle(out)

    @app.get("/fhir/Patient/{pid}")
    def get_patient(pid: str):
        return patients.get(pid) or outcome(404, f"Patient/{pid} not found")

    @app.get("/fhir/RelatedPerson")
    def search_related(patient: str):
        return bundle([r for r in related if r["patient"]["reference"] == patient])

    @app.get("/fhir/Practitioner")
    def list_practitioners():
        return bundle([{"resourceType": "Practitioner", "id": p["id"],
                        "name": [{"text": p["name"]}]} for p in PRACTITIONERS])

    @app.get("/fhir/Slot")
    def search_slots(status: str | None = None,
                     service_type: str | None = Query(None, alias="service-type"),
                     start: list[str] = Query(default=[])):
        out = []
        for s in slots.values():
            if status and s["status"] != status:
                continue
            if service_type and s["serviceType"][0]["text"] != service_type:
                continue
            ok = True
            for cond in start:  # FHIR date prefixes: ge2026-11-16T08:00, lt...
                op, value = cond[:2], datetime.fromisoformat(cond[2:]).replace(tzinfo=None)
                st = datetime.fromisoformat(s["start"])
                ok &= {"ge": st >= value, "gt": st > value, "lt": st < value, "le": st <= value}[op]
            if ok:
                out.append(s)
        return bundle(sorted(out, key=lambda s: s["start"]))

    @app.post("/fhir/Appointment", status_code=201)
    def create_appointment(appt: dict = Body(...)):
        sid = appt["slot"][0]["reference"].split("/")[1]
        slot = slots.get(sid) or outcome(404, f"Slot/{sid} not found")
        if slot["status"] != "free":
            outcome(409, "Slot is no longer free")  # someone else booked it first
        slot["status"] = "busy"
        aid = f"ap-{6000 + len(appointments)}"
        practitioner = slot["schedule"]["reference"].replace("Schedule/", "Practitioner/")
        appt.update(id=aid, resourceType="Appointment", status="booked",
                    start=slot["start"], end=slot["end"])
        appt["participant"] = appt.get("participant", []) + [{"actor": {"reference": practitioner}}]
        appointments[aid] = appt
        return appt

    @app.get("/fhir/Appointment")
    def search_appointments(patient: str | None = None, status: str | None = None):
        out = [a for a in appointments.values()
               if (not status or a["status"] == status)
               and (not patient or any(p["actor"]["reference"] == patient for p in a["participant"]))]
        return bundle(sorted(out, key=lambda a: a["start"]))

    @app.get("/fhir/Appointment/{aid}")
    def get_appointment(aid: str):
        return appointments.get(aid) or outcome(404, f"Appointment/{aid} not found")

    @app.put("/fhir/Appointment/{aid}")
    def update_appointment(aid: str, appt: dict = Body(...)):
        old = appointments.get(aid) or outcome(404, f"Appointment/{aid} not found")
        if appt.get("status") == "cancelled" and old["status"] == "booked":
            slots[old["slot"][0]["reference"].split("/")[1]]["status"] = "free"
        appointments[aid] = {**appt, "id": aid}
        return appointments[aid]

    @app.post("/fhir/Task", status_code=201)
    def create_task(task: dict = Body(...)):
        tid = f"tk-{len(tasks) + 1}"
        tasks[tid] = {**task, "resourceType": "Task", "id": tid, "status": "requested",
                      "authoredOn": clock().isoformat(timespec="minutes")}
        return tasks[tid]

    @app.get("/fhir/Task")
    def search_tasks(status: str | None = None):
        return bundle([t for t in tasks.values() if not status or t["status"] == status])

    return app


app = create_app()
