"""Fake data for Maple Court Apartments (fictional).

48 units: 4 floors x 12 units, named 1A..4L. Phone numbers use the 555-01xx
range, which is reserved for fiction. Add your own number to DEMO_TENANTS
to test calls from your phone.
"""

import random

BUILDING = {
    "Id": 1,
    "Name": "Maple Court Apartments",
    "Address": "1200 W Maple Ct, Chicago, IL 60626",
    "HeatSource": "Central steam boiler (one for the whole building)",
    "WaterShutoff": "Each unit has a shutoff valve under the kitchen sink. Main shutoff is in the basement boiler room.",
}

FIRST = ["Maria", "James", "Aisha", "Wei", "Carlos", "Fatima", "Tom", "Grace",
         "Omar", "Sofia", "Daniel", "Mei", "Andre", "Hannah", "Raj", "Elena"]
LAST = ["Lopez", "Johnson", "Khan", "Chen", "Rivera", "Ali", "Murphy", "Kim",
        "Haddad", "Rossi", "Brooks", "Wang", "Davis", "Novak", "Patel", "Garcia"]

# Put your own number here (E.164 format, e.g. "+12175550123") to be recognized
# as a tenant when you call the agent.
DEMO_TENANTS = [
    # {"FirstName": "Meghna", "LastName": "Test", "Phone": "+1XXXXXXXXXX", "Unit": "2C"},
]

STAFF = [
    {"Id": 1, "FirstName": "Dana", "LastName": "Okafor", "Role": "Property Manager", "Phone": "+13125550101"},
    {"Id": 2, "FirstName": "Luis", "LastName": "Mendez", "Role": "Maintenance Technician", "Phone": "+13125550102"},
    {"Id": 3, "FirstName": "Priya", "LastName": "Shah", "Role": "Maintenance Technician", "Phone": "+13125550103"},
]


def build():
    rng = random.Random(42)  # fixed seed so the data is the same every run
    units, tenants = [], []
    unit_id = 0
    for floor in range(1, 5):
        for letter in "ABCDEFGHIJKL":
            unit_id += 1
            name = f"{floor}{letter}"
            units.append({
                "Id": unit_id,
                "PropertyId": 1,
                "UnitNumber": name,
                "Bedrooms": rng.choice([1, 1, 2, 2, 3]),
                "Bathrooms": rng.choice([1, 1, 1, 2]),
            })
            tenants.append({
                "Id": unit_id,
                "FirstName": rng.choice(FIRST),
                "LastName": rng.choice(LAST),
                "PhoneNumbers": [{"Number": f"+1312555{1000 + unit_id:04d}", "Type": "Cell"}],
                "UnitId": unit_id,
            })

    by_name = {u["UnitNumber"]: u["Id"] for u in units}
    for i, t in enumerate(DEMO_TENANTS):
        tenants.append({
            "Id": 1000 + i,
            "FirstName": t["FirstName"],
            "LastName": t["LastName"],
            "PhoneNumbers": [{"Number": t["Phone"], "Type": "Cell"}],
            "UnitId": by_name[t["Unit"]],
        })

    return units, tenants
