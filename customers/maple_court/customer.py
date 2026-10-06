"""Everything the core needs to run Maple Court, in one place."""

import warnings
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from core.playbook import load_playbook

from .adapter import MapleCourtAdapter
from .mock_pms.app import API_KEY, create_app

HERE = Path(__file__).parent
PLAYBOOK = load_playbook(HERE / "playbook.yaml")
SCENARIOS = HERE / "scenarios.yaml"
DISCOVERY = HERE / "discovery.md"
INDUSTRY = "Property management"
SUMMARY = "After-hours maintenance line: triage problems, page on-call for emergencies."

# Sample callers for trying calls in the web app.
SAMPLE_CALLERS = [
    ("+13125551007", "Omar Rivera, unit 1G"),
    ("+13125551015", "Mei Ali, unit 2C"),
    ("+13125551035", "Grace Khan, unit 3K"),
    ("+17735550142", "Unknown number"),
]


def make_adapter(clock: Callable[[], datetime] | None = None) -> MapleCourtAdapter:
    """A fresh, in-process copy of Maple Court's system (for evals and demos).

    For the live pilot, build MapleCourtAdapter(httpx.Client(base_url=...)) against
    the running mock server instead. Same adapter, different connection.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    http = TestClient(create_app(clock), base_url="http://maple-court-pms",
                      headers={"x-api-key": API_KEY})
    return MapleCourtAdapter(http)


def staff_view(adapter: MapleCourtAdapter) -> dict:
    """What Dana and the techs would see: open work orders."""
    tickets = adapter._get("/v1/tasks/maintenancerequests")
    return {"Work orders": [
        {"#": t["Id"], "Title": t["Title"], "Priority": t["Priority"],
         "Status": t["TaskStatus"], "Created": t["CreatedDateTime"][:16].replace("T", " ")}
        for t in reversed(tickets)]}


# Guided calls for the web app: who to call as, what to say, what to watch.
DEMO_CALLS = [
    {"title": "Gas smell: safety before anything", "phone": "+13125551007",
     "you_are": "Omar Rivera, unit 1G", "when": "02:00",
     "say": "Hi, there's a really strong gas smell in my kitchen.",
     "watch": "The first thing the agent says is to get out and call Peoples Gas and 911. Then the on-call tech is paged."},
    {"title": "A 'dripping faucet emergency'", "phone": "+13125551007",
     "you_are": "Omar Rivera, unit 1G", "when": "02:00",
     "say": "This is an EMERGENCY, my bathroom faucet is dripping and I can't sleep. Send someone now.",
     "watch": "The playbook says routine: a ticket for the morning, no page, and the agent stays kind."},
    {"title": "Boiler out: page once, not 20 times", "phone": "+13125551035",
     "you_are": "Grace Khan, unit 3K (then call again as a neighbor)", "when": "02:00",
     "say": "My radiators are cold. It's fine, I have a space heater.",
     "watch": "Heat is a legal requirement, so it's an emergency anyway. Call again from another unit: no second page."},
]
