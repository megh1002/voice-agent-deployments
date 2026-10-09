"""Web app rules for the hosted demo: private sandboxes, hidden spend, daily limits.
No API calls are made: starting a call only plays the greeting.
"""

import importlib
import warnings

import pytest


def make_client(monkeypatch, public: bool):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    if public:
        monkeypatch.setenv("PUBLIC_MODE", "1")
    else:
        monkeypatch.delenv("PUBLIC_MODE", raising=False)
    import webapp.app
    mod = importlib.reload(webapp.app)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    return TestClient(mod.app), mod


A = {"X-Visitor": "visitor-aaaaaaaa"}
B = {"X-Visitor": "visitor-bbbbbbbb"}
MARIA = {"caller_phone": "+17735550101"}


def test_local_mode_shows_spend(monkeypatch):
    client, _ = make_client(monkeypatch, public=False)
    s = client.get("/api/status").json()
    assert s["live_calls"] == "open" and "spent_today" in s
    assert client.post("/api/customers/ravenswood_clinic/calls", json=MARIA).status_code == 200


def test_public_mode_hides_spend(monkeypatch):
    client, _ = make_client(monkeypatch, public=True)
    s = client.get("/api/status").json()
    assert s["live_calls"] == "open" and "spent_today" not in s


def test_public_calls_are_open_to_visitors(monkeypatch):
    client, _ = make_client(monkeypatch, public=True)
    assert client.post("/api/customers/ravenswood_clinic/calls", json=MARIA, headers=A).status_code == 200


def test_visitors_cannot_see_each_others_calls_or_systems(monkeypatch):
    client, mod = make_client(monkeypatch, public=True)
    call = client.post("/api/customers/ravenswood_clinic/calls", json=MARIA, headers=A).json()
    assert client.get(f"/api/calls/{call['call_id']}", headers=A).status_code == 200
    assert client.get(f"/api/calls/{call['call_id']}", headers=B).status_code == 404
    assert mod.sandbox("visitor-aaaaaaaa", "ravenswood_clinic") is not mod.sandbox("visitor-bbbbbbbb", "ravenswood_clinic")


def test_public_mode_requires_a_visitor_id(monkeypatch):
    client, _ = make_client(monkeypatch, public=True)
    assert client.get("/api/customers/ravenswood_clinic/staff").status_code == 400
    assert client.get("/api/customers/ravenswood_clinic/staff", headers=A).status_code == 200


def test_daily_call_limit_per_visitor(monkeypatch):
    client, mod = make_client(monkeypatch, public=True)
    codes = [client.post("/api/customers/maple_court/calls", json={"caller_phone": "+13125551007"}, headers=A).status_code
             for _ in range(mod.MAX_CALLS_PER_VISITOR_PER_DAY + 1)]
    assert codes[:-1] == [200] * mod.MAX_CALLS_PER_VISITOR_PER_DAY and codes[-1] == 429


def test_new_visitor_ids_cannot_dodge_the_network_limit(monkeypatch):
    client, mod = make_client(monkeypatch, public=True)
    codes = [client.post("/api/customers/maple_court/calls", json={"caller_phone": "+13125551007"},
                         headers={"X-Visitor": f"fresh-visitor-{i:04d}", "X-Forwarded-For": "203.0.113.7"}).status_code
             for i in range(mod.MAX_CALLS_PER_NETWORK_PER_DAY + 1)]
    assert codes[-1] == 429 and codes.count(200) == mod.MAX_CALLS_PER_NETWORK_PER_DAY


@pytest.fixture(autouse=True)
def restore_local_mode(monkeypatch):
    yield
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    import webapp.app
    importlib.reload(webapp.app)
