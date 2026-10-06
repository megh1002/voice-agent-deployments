"""Maple Court's integration: their property management system + on-call sheet.

Implements core.adapter.CustomerAdapter. Talks to the PMS over HTTP only, so
pointing it at the real Buildium later means changing the base URL and auth,
not the logic.
"""

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from core.adapter import Caller, Contact

ONCALL_CSV = Path(__file__).parent / "oncall_schedule.csv"


class MapleCourtAdapter:
    def __init__(self, http: httpx.Client, oncall_csv: Path = ONCALL_CSV):
        self.http = http
        self.oncall_csv = oncall_csv
        self._units: dict[int, str] | None = None

    def _get(self, path: str, **params):
        r = self.http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def _unit_names(self) -> dict[int, str]:
        if self._units is None:
            self._units = {u["Id"]: u["UnitNumber"] for u in self._get("/v1/rentals/units")}
        return self._units

    def _unit_id(self, unit: str) -> int | None:
        unit = unit.strip().upper().replace("UNIT", "").replace(" ", "")
        for uid, name in self._unit_names().items():
            if name == unit:
                return uid
        return None

    # ---- CustomerAdapter ------------------------------------------------------

    def find_caller(self, phone: str) -> Caller | None:
        matches = self._get("/v1/rentals/tenants", phone=phone)
        if not matches:
            return None
        t = matches[0]
        return Caller(name=f"{t['FirstName']} {t['LastName']}",
                      unit=self._unit_names().get(t["UnitId"]), phone=phone)

    def unit_exists(self, unit: str) -> bool:
        return self._unit_id(unit) is not None

    def create_ticket(self, *, title, description, category, priority, unit) -> str:
        r = self.http.post("/v1/tasks/maintenancerequests", json={
            "Title": title, "Description": description, "Category": category,
            "Priority": priority, "UnitId": self._unit_id(unit) if unit else None,
        })
        r.raise_for_status()
        return str(r.json()["Id"])

    def open_emergency_since(self, category: str, since: datetime) -> str | None:
        for r in self._get("/v1/tasks/maintenancerequests", status="New"):
            if (r["Category"] == category and r["Title"].startswith("[EMERGENCY]")
                    and datetime.fromisoformat(r["CreatedDateTime"]) >= since):
                return str(r["Id"])
        return None

    def on_call(self, when: datetime) -> tuple[Contact, Contact]:
        staff = {s["Id"]: s for s in self._get("/v1/users")}

        def contact(user_id: str) -> Contact:
            s = staff[int(user_id)]
            return Contact(name=f"{s['FirstName']} {s['LastName']}", phone=s["Phone"])

        today = when.date()
        with self.oncall_csv.open() as f:
            for row in csv.DictReader(f):
                start = date.fromisoformat(row["week_start"])
                if start <= today < start + timedelta(days=7):
                    return contact(row["primary_user_id"]), contact(row["backup_user_id"])
        # Schedule ran out: a real gap Dana needs to know about. Fall back to her.
        dana = contact("1")
        return dana, dana
