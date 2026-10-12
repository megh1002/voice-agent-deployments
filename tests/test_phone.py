"""The Vapi phone endpoint: auth, one agent session per call, OpenAI-style streaming.
The model is scripted, so no API calls are made.
"""

import importlib
import json
import warnings
from types import SimpleNamespace as NS

from core import llm


def client_with_secret(monkeypatch, secret="phone-secret"):
    monkeypatch.setenv("VAPI_SECRET", secret)
    monkeypatch.delenv("PUBLIC_MODE", raising=False)
    import webapp.app
    mod = importlib.reload(webapp.app)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    return TestClient(mod.app), mod


def vapi_body(call_id, *turns, stream=True):
    messages = [{"role": "system", "content": "(vapi system prompt, ignored)"},
                {"role": "assistant", "content": "Thanks for calling Ravenswood Family Medicine..."}]
    for t in turns:
        messages.append({"role": "user", "content": t})
    return {"model": "custom", "stream": stream, "messages": messages,
            "call": {"id": call_id, "customer": {"number": "+15555550123"}}}


def scripted(*replies):
    replies = iter(replies)
    return lambda **kw: NS(stop_reason="end_turn", content=[NS(type="text", text=next(replies))])


AUTH = {"Authorization": "Bearer phone-secret"}


def test_phone_is_off_without_a_secret(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.delenv("VAPI_SECRET")
    assert client.post("/vapi/chat/completions", json=vapi_body("c1", "hi")).status_code == 503


def test_wrong_secret_is_rejected(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    r = client.post("/vapi/chat/completions", json=vapi_body("c1", "hi"), headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_turns_on_the_same_call_share_one_session(monkeypatch):
    client, mod = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", scripted("How can I help?", "Sure, what's your date of birth?"))
    r1 = client.post("/vapi/chat/completions", json=vapi_body("call-abc", "Hi"), headers=AUTH)
    r2 = client.post("/vapi/chat/completions", json=vapi_body("call-abc", "Hi", "I want to cancel"), headers=AUTH)
    assert r1.status_code == r2.status_code == 200
    chunks = [json.loads(l[6:]) for l in r2.text.splitlines() if l.startswith("data: {")]
    assert chunks[0]["choices"][0]["delta"]["content"].strip() == "Sure, what's your date of birth?"
    assert r2.text.rstrip().endswith("data: [DONE]")
    session = mod.PHONE_CALLS["call-abc"]
    assert [t["text"] for t in session.record["transcript"] if t["speaker"] == "caller"] == ["Hi", "I want to cancel"]
    assert len(session.record["latencies_s"]) == 2


def test_non_streaming_response(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", scripted("Hello there."))
    r = client.post("/vapi/chat/completions", json=vapi_body("c2", "Hi", stream=False), headers=AUTH)
    assert r.json()["choices"][0]["message"]["content"].strip() == "Hello there."


def test_no_new_caller_words_means_no_model_call(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", lambda **kw: (_ for _ in ()).throw(AssertionError("should not call")))
    body = vapi_body("c3")  # ends with the assistant's greeting
    r = client.post("/vapi/chat/completions", json=body, headers=AUTH)
    assert r.status_code == 200


def teardown_module():
    import webapp.app
    importlib.reload(webapp.app)


def test_secret_accepted_in_common_formats(monkeypatch):
    client, _ = client_with_secret(monkeypatch)
    monkeypatch.setattr(llm, "create", scripted("a", "b", "c", "d"))
    for i, headers in enumerate([{"Authorization": "Bearer phone-secret"}, {"Authorization": "phone-secret"},
                                 {"X-Api-Key": "phone-secret"}, {"Authorization": "Bearer Bearer phone-secret"}]):
        assert client.post("/vapi/chat/completions", json=vapi_body(f"fmt{i}", "hi"), headers=headers).status_code == 200
    assert client.post("/vapi/chat/completions", json=vapi_body("fmtx", "hi"),
                       headers={"X-Api-Key": "wrong"}).status_code == 401


def test_page_can_follow_a_voice_call(monkeypatch):
    client, mod = client_with_secret(monkeypatch)
    monkeypatch.setenv("VAPI_PUBLIC_KEY", "pub-key"); monkeypatch.setenv("VAPI_ASSISTANT_ID", "asst-1")
    assert client.get("/api/status").json()["vapi"] == {"public_key": "pub-key", "assistant_id": "asst-1",
                                                       "customer": "ravenswood_clinic"}
    assert client.get("/api/voice/calls/nope").json() == {"found": False}
    monkeypatch.setattr(llm, "create", scripted("How can I help?"))
    client.post("/vapi/chat/completions", json=vapi_body("live-1", "Hi"), headers=AUTH)
    v = client.get("/api/voice/calls/live-1").json()
    assert v["found"] and v["transcript"][-1]["text"] == "How can I help?" and "Staff queues" in v["staff"]["tables"]


def test_slow_turn_says_one_moment_first(monkeypatch):
    import time as _time
    client, mod = client_with_secret(monkeypatch)
    monkeypatch.setattr(mod, "FILLER_AFTER_S", 0.2)
    def slow(**kw):
        _time.sleep(0.6)
        return NS(stop_reason="end_turn", content=[NS(type="text", text="Here's your answer.")])
    monkeypatch.setattr(llm, "create", slow)
    r = client.post("/vapi/chat/completions", json=vapi_body("slow-1", "Hi"), headers=AUTH)
    said = [json.loads(l[6:])["choices"][0]["delta"].get("content", "").strip()
            for l in r.text.splitlines() if l.startswith("data: {")]
    assert said[:2] == ["One moment.", "Here's your answer."]
    rec = mod.PHONE_CALLS["slow-1"].record
    assert rec["fillers"] == 1 and rec["first_words_s"][0] < rec["latencies_s"][0]
