"""End-to-end check of the eval pipeline with a scripted fake model (no API key).

Proves the plumbing works: caller -> agent -> tool -> workflow -> mock system ->
texts -> call record -> code checks -> judge -> report.
"""

import json
from types import SimpleNamespace as NS

import pytest
import yaml

from core import llm
from customers import CUSTOMERS
from customers.maple_court import customer as mc
from evals import run


def text(t):
    return NS(type="text", text=t)


def tool(name, **inp):
    return NS(type="tool_use", name=name, input=inp, id=f"tu_{name}")


def scripted_model(caller_lines, agent_turns):
    caller_lines, agent_turns = iter(caller_lines), iter(agent_turns)

    def fake_create(*, effort, **kw):
        system = kw.get("system", "")
        if "role-playing" in system:
            return NS(stop_reason="end_turn", content=[text(next(caller_lines))])
        if system.startswith("You grade"):
            n = len([l for l in kw["messages"][0]["content"].splitlines() if l[:1].isdigit()])
            return NS(stop_reason="end_turn", content=[text(json.dumps({"criteria": [
                {"criterion": f"c{i}", "passed": True, "evidence": "ok"} for i in range(n)]}))])
        return next(agent_turns)

    return fake_create


def test_maple_court_gas_call_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "create", scripted_model(
        ["I smell gas in my kitchen, really strong.", "Okay, going now. Bye. [HANGUP]"],
        [NS(stop_reason="tool_use", content=[
            text("Please leave the building right now and call Peoples Gas and 911 from outside."),
            tool("report_issue", category="gas_smell", summary="Strong gas smell", unit="1G")]),
         NS(stop_reason="end_turn", content=[text("The on-call technician has been paged.")]),
         NS(stop_reason="tool_use", content=[text("Stay safe. Goodbye."), tool("end_call")])]))
    spec = yaml.safe_load(mc.SCENARIOS.read_text())
    sc = next(s for s in spec["scenarios"] if s["id"] == "gas_inside")

    record = run.run_scenario(mc, sc, spec["defaults"], tmp_path)

    assert record["transcript"][0]["text"] == mc.PLAYBOOK.disclosure
    assert record["events"][0]["paged"] == "Priya Shah"
    assert all(c["passed"] for c in record["code_checks"]), record["code_checks"]
    assert record["passed"]
    assert "Safety-critical calls fully passed:** 1/1" in run.summarize([record])


def test_duplicate_setup_suppresses_second_page(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "create", scripted_model(
        ["My radiators are ice cold.", "Fine. Bye. [HANGUP]"],
        [NS(stop_reason="tool_use", content=[
            tool("report_issue", category="no_heat", summary="No heat", unit="3F")]),
         NS(stop_reason="end_turn", content=[text("This has already been reported.")]),
         NS(stop_reason="tool_use", content=[text("Goodbye."), tool("end_call")])]))
    spec = yaml.safe_load(mc.SCENARIOS.read_text())
    sc = next(s for s in spec["scenarios"] if s["id"] == "no_heat_already_reported")
    record = run.run_scenario(mc, sc, spec["defaults"], tmp_path)
    assert record["events"][0]["duplicate_of"] is not None
    assert all(c["passed"] for c in record["code_checks"]), record["code_checks"]


@pytest.mark.parametrize("name", CUSTOMERS)
def test_every_scenario_is_well_formed(name):
    customer = run.load_customer(name)
    spec = yaml.safe_load(customer.SCENARIOS.read_text())
    ids = [s["id"] for s in spec["scenarios"]]
    assert len(ids) == len(set(ids))
    known = {"level", "paged", "category", "verified", "booked", "rescheduled", "cancelled",
             "waitlist_offered", "handoff", "red_flag", "stays_on_line", "must", "must_not"}
    for s in spec["scenarios"]:
        assert set(s["expect"]) <= known, (s["id"], set(s["expect"]) - known)
        assert s["group"] and s["persona"] and s["caller_phone"]


def test_failed_api_call_rolls_back_the_turn(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import anthropic, httpx
    from core.agent import CallSession
    from core.notifier import Notifier
    from customers.ravenswood_clinic import customer as rc

    def boom(**kw):
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    monkeypatch.setattr(llm, "create", boom)
    now = datetime(2026, 11, 16, 8, 5, tzinfo=ZoneInfo("America/Chicago"))
    call = CallSession(rc.PLAYBOOK, rc.make_adapter(lambda: now), Notifier("outbox", tmp_path / "o"), "+1", now)
    call.start()
    before = (len(call.messages), len(call.record["transcript"]))
    with pytest.raises(anthropic.APIConnectionError):
        call.reply("hello")
    assert (len(call.messages), len(call.record["transcript"])) == before


def test_budget_ledger(tmp_path, monkeypatch):
    from core import budget
    monkeypatch.setattr(budget, "LEDGER", tmp_path / "spend.jsonl")
    monkeypatch.setenv("DAILY_BUDGET_USD", "0.10")
    budget.record(0.06, "webapp"); budget.record(0.50, "eval")
    assert budget.spent(source="webapp") == 0.06 and not budget.over_budget()
    budget.record(0.05, "webapp")
    assert budget.over_budget()
