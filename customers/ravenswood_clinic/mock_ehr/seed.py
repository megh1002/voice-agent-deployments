"""Synthetic data for Ravenswood Family Medicine (fictional). No real patients.

Phone numbers use the 555-01xx range reserved for fiction. Slots are generated
for two weeks from the clock's date, so the schedule always looks current.
"""

import random
from datetime import date, datetime, time, timedelta

PRACTITIONERS = [
    {"id": "pr-morales", "name": "Dr. Ana Morales"},
    {"id": "pr-becker", "name": "Dr. Tom Becker"},
    {"id": "pr-raman", "name": "Dr. Nadia Raman"},
    {"id": "pr-grant", "name": "Dr. Wesley Grant"},
    {"id": "pr-cho", "name": "Lauren Cho, NP"},
]

VISIT_TYPES = ["follow_up", "same_day_sick", "annual_physical", "new_patient"]

# Patients the eval scenarios use. (given, family, birthDate, phone, address, proxies)
KEY_PATIENTS = [
    ("pt-1001", "Maria", "Gonzalez", "1958-03-14", "+17735550101", "4512 N Damen Ave", ["Lucia Gonzalez"]),
    ("pt-1002", "David", "Chen", "1985-07-22", "+17735550102", "1830 W Montrose Ave", []),
    ("pt-1003", "Ethan", "Park", "2019-05-02", "+17735550103", "2240 W Leland Ave", ["Grace Park"]),
    ("pt-1004", "Robert", "Johnson", "1949-11-30", "+17735550104", "4701 N Ravenswood Ave", []),
    ("pt-1005", "Aisha", "Bello", "1992-01-09", "+17735550105", "1500 W Wilson Ave", []),
    ("pt-1006", "Samuel", "Okoro", "1970-08-18", "+17735550106", "4600 N Hermitage Ave", []),
    ("pt-1007", "Linda", "Novak", "1963-12-05", "+17735550107", "2100 W Lawrence Ave", []),
    ("pt-1008", "Maria", "Gonzalez", "1990-06-30", "+17735550108", "5020 N Lincoln Ave", []),  # same name, different person
    ("pt-1009", "Kwame", "Mensah", "1978-02-17", "+17735550109", "4300 N Western Ave", []),
]

FIRST = ["Ana", "Ben", "Chloe", "Dev", "Elena", "Femi", "Gus", "Hana", "Ivan", "Jade", "Kofi", "Lena"]
LAST = ["Adams", "Bauer", "Cruz", "Diaz", "Evans", "Fox", "Gupta", "Hale", "Ito", "Jones", "Klein", "Lim"]


def _patient(pid, given, family, dob, phone, address):
    return {
        "resourceType": "Patient", "id": pid,
        "name": [{"given": [given], "family": family}],
        "birthDate": dob,
        "telecom": [{"system": "phone", "value": phone}],
        "address": [{"line": [address], "city": "Chicago", "state": "IL"}],
    }


def build(today: date):
    rng = random.Random(7)
    patients, related = {}, []
    for pid, given, family, dob, phone, address, proxies in KEY_PATIENTS:
        patients[pid] = _patient(pid, given, family, dob, phone, address)
        for proxy in proxies:
            pg, pf = proxy.split()
            related.append({"resourceType": "RelatedPerson", "id": f"rp-{pid}-{pg.lower()}",
                            "patient": {"reference": f"Patient/{pid}"},
                            "name": [{"given": [pg], "family": pf}],
                            "relationship": [{"text": "authorized representative"}]})
    for i in range(30):
        pid = f"pt-2{i:03d}"
        patients[pid] = _patient(pid, rng.choice(FIRST), rng.choice(LAST),
                                 f"{rng.randint(1940, 2015)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                                 f"+1773555{3000 + i:04d}", f"{rng.randint(1000, 5999)} N Clark St")

    # 20-minute slots, 9:00 to 16:40, weekdays, for two weeks. About 70% already taken.
    slots = {}
    for d in range(15):
        day = today + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        for pr in PRACTITIONERS:
            t = datetime.combine(day, time(9, 0))
            while t.time() < time(17, 0):
                sid = f"sl-{pr['id'][3:]}-{t:%m%d%H%M}"
                vt = rng.choices(VISIT_TYPES, weights=[45, 25, 20, 10])[0]
                if d == 0 and t.hour < 12:
                    vt = "same_day_sick"  # mornings today are held for sick visits
                slots[sid] = {
                    "resourceType": "Slot", "id": sid,
                    "schedule": {"reference": f"Schedule/{pr['id']}"},
                    "serviceType": [{"text": vt}],
                    "status": "busy" if rng.random() < 0.7 else "free",
                    "start": t.isoformat(), "end": (t + timedelta(minutes=20)).isoformat(),
                }
                t += timedelta(minutes=20)

    # Existing appointments the scenarios rely on.
    appointments = {}

    def book(aid, pid, pr_id, day_offset, hh, mm, vt):
        day = today + timedelta(days=day_offset)
        while day.weekday() >= 5:
            day += timedelta(days=1)
        t = datetime.combine(day, time(hh, mm))
        sid = f"sl-{pr_id[3:]}-{t:%m%d%H%M}"
        slots[sid].update(status="busy", serviceType=[{"text": vt}])
        appointments[aid] = {
            "resourceType": "Appointment", "id": aid, "status": "booked",
            "serviceType": [{"text": vt}], "slot": [{"reference": f"Slot/{sid}"}],
            "start": slots[sid]["start"], "end": slots[sid]["end"],
            "participant": [{"actor": {"reference": f"Patient/{pid}"}},
                            {"actor": {"reference": f"Practitioner/{pr_id}"}}],
        }

    book("ap-5001", "pt-1001", "pr-morales", 3, 10, 0, "follow_up")       # Maria G.
    book("ap-5002", "pt-1004", "pr-becker", 5, 9, 0, "annual_physical")   # Robert J.
    book("ap-5003", "pt-1003", "pr-cho", 2, 15, 20, "follow_up")          # Ethan P.
    return patients, related, slots, appointments
