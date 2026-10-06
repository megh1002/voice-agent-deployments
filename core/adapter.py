"""The data shapes customer systems hand back to the core.

Every customer stores data somewhere different (a property management system,
an EHR, a spreadsheet). Each customer folder has an adapter that talks to those
systems and returns these plain shapes, so the core never cares where data lives.
Each workflow module's docstring lists the adapter methods it needs.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Caller:
    name: str
    unit: str | None
    phone: str


@dataclass
class Contact:
    name: str
    phone: str


@dataclass
class PatientRecord:
    id: str
    name: str
    birth_date: str          # YYYY-MM-DD
    phone: str
    address_line: str
    proxies: list[str] = field(default_factory=list)  # people authorized to act for them


@dataclass
class SlotInfo:
    id: str
    start: datetime
    clinician: str
    visit_type: str


@dataclass
class AppointmentInfo:
    id: str
    start: datetime
    clinician: str
    visit_type: str
    slot_id: str
