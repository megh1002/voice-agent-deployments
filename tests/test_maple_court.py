"""Maple Court (triage workflow): rules, routing, integration, guardrails.
No API key needed. Run: .venv/bin/pytest -q
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from core.notifier import Notifier
from customers.maple_court import customer as mc

from .conftest import make_call, sent, use_tool

CHI = ZoneInfo("America/Chicago")
NOV_2AM = datetime(2026, 11, 20, 2, 0, tzinfo=CHI)    # heating season
JULY_2AM = datetime(2026, 7, 10, 2, 0, tzinfo=CHI)    # not heating season
OMAR = "+13125551007"                                 # Omar Rivera, 1G


def triage(call):
    return next(w for w in call.workflows if w.name == "triage")


def report(call, category, unit="1G"):
    return use_tool(call, "report_issue", category=category, summary="test", unit=unit)


def test_every_category_has_a_valid_level(outbox):
    rules = triage(make_call(mc, OMAR, NOV_2AM, outbox)).rules
    assert all(c.level in rules.levels for c in rules.categories)


def test_heat_is_emergency_in_season_and_routine_out_of_season(outbox):
    rules = triage(make_call(mc, OMAR, NOV_2AM, outbox)).rules
    assert rules.resolve_level("no_heat", NOV_2AM)[0] == "emergency"
    assert rules.resolve_level("no_heat", JULY_2AM)[0] == "routine"
    assert rules.resolve_level("no_heat", datetime(2026, 9, 15, tzinfo=CHI))[0] == "emergency"
    assert rules.resolve_level("no_heat", datetime(2026, 6, 1, tzinfo=CHI))[0] == "routine"


def test_caller_id_is_used_for_tenants(outbox):
    call = make_call(mc, OMAR, NOV_2AM, outbox)
    assert call.state["caller"].unit == "1G"
    assert "Omar Rivera" in call.messages[0]["content"]
    unknown = make_call(mc, "+19999999999", NOV_2AM, outbox)
    assert "not on file" in unknown.messages[0]["content"]


def test_unit_check_and_on_call_rotation(outbox):
    call = make_call(mc, OMAR, NOV_2AM, outbox)
    assert use_tool(call, "verify_unit", unit="Unit 4L")["exists"]
    assert not use_tool(call, "verify_unit", unit="9Z")["exists"]
    primary, backup = call.adapter.on_call(NOV_2AM)
    assert primary.name == "Priya Shah" and backup.name == "Dana Okafor"


def test_emergency_pages_on_call_and_texts_confirmation(outbox):
    call = make_call(mc, OMAR, NOV_2AM, outbox)
    result = report(call, "gas_smell")
    assert result["level"] == "emergency"
    assert call.events("report")[0]["paged"] == "Priya Shah"
    texts = sent(outbox)
    assert len(texts) == 2 and "EMERGENCY" in texts[0]["body"]


def test_boiler_out_pages_once_for_many_callers(outbox):
    adapter = mc.make_adapter(lambda: NOV_2AM)
    from core.agent import CallSession
    first = CallSession(mc.PLAYBOOK, adapter, Notifier("outbox", outbox), OMAR, NOV_2AM)
    first.start()
    report(first, "no_heat", unit="1A")
    second = CallSession(mc.PLAYBOOK, adapter, Notifier("outbox", outbox), "+13125551030", NOV_2AM)
    second.start()
    r = report(second, "no_heat", unit="3F")
    assert first.events("report")[0]["paged"]
    assert second.events("report")[0]["paged"] is None
    assert "already been reported" in r["tell_caller"]


def test_urgent_creates_ticket_without_paging(outbox):
    call = make_call(mc, OMAR, NOV_2AM, outbox)
    assert report(call, "no_hot_water")["level"] == "urgent"
    assert call.events("report")[0]["paged"] is None
    assert not any("EMERGENCY" in t["body"] for t in sent(outbox))


def test_failed_page_tells_caller_the_truth(outbox, monkeypatch):
    monkeypatch.setattr(Notifier, "send_sms", lambda self, to, body: False)
    call = make_call(mc, OMAR, NOV_2AM, outbox)
    assert "wasn't able to reach" in report(call, "active_flooding")["tell_caller"]


def test_guardrails(outbox):
    call = make_call(mc, OMAR, NOV_2AM, outbox)
    from core.guardrails import check_reply
    assert check_reply("The technician has been paged.", call)[0]["rule"] == "claimed_page_without_page"
    assert check_reply("That usually costs about $150.", call)[0]["rule"] == "cost_estimate"
    report(call, "gas_smell")
    assert check_reply("The technician has been paged.", call) == []
    assert check_reply("Someone will be there within 30 minutes.", call)[0]["rule"] == "promised_time"
